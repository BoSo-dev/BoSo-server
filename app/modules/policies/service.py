import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.policies import repository
from app.modules.policies.models import Policy, PolicyAction, PolicySource, PolicyVersion
from app.modules.policies.schemas import (
    PolicyActionSnapshot,
    PolicyImportFile,
    PolicySnapshot,
    PolicySourceInput,
    PolicyVersionInput,
)


class PolicyImportError(ValueError):
    """Only a fixed code is exposed; input and database values stay private."""


def today_kst():
    return (datetime.now(UTC) + timedelta(hours=9)).date()


def validate_reviews(batch: PolicyImportFile, today: date | None = None):
    today = today or today_kst()
    if any(item.reviewed_on > today for item in batch.policies):
        raise PolicyImportError("POLICY_FUTURE_REVIEW")


def content_hash(item: PolicyVersionInput):
    payload = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def import_policies(db: Session, batch: PolicyImportFile):
    """Caller owns the transaction. Never commit individual records here."""
    validate_reviews(batch)
    counts = {"created": 0, "unchanged": 0}
    # Stable lock order avoids deadlocks between overlapping multi-policy files.
    for item in sorted(batch.policies, key=lambda item: item.policy_key):
        policy = repository.lock_policy(db, item.policy_key, item.is_example)
        if policy.is_example != item.is_example:
            raise PolicyImportError("POLICY_EXAMPLE_CONFLICT")
        history = repository.versions(db, policy.id)
        digest = content_hash(item)
        existing = next((row for row in history if row.version == item.version), None)
        if existing:
            if existing.content_hash != digest:
                raise PolicyImportError("POLICY_VERSION_IMMUTABLE")
            counts["unchanged"] += 1
            continue
        latest = history[0] if history else None
        if item.version != (latest.version + 1 if latest else 1):
            raise PolicyImportError("POLICY_VERSION_SEQUENCE")
        if latest and item.effective_from < latest.effective_from:
            raise PolicyImportError("POLICY_EFFECTIVE_ORDER")
        if latest and item.reviewed_on < latest.reviewed_on:
            raise PolicyImportError("POLICY_REVIEW_ORDER")
        values = item.model_dump(exclude={"policy_key", "is_example", "sources", "actions"})
        row = PolicyVersion(policy_id=policy.id, content_hash=digest, **values)
        row.sources = [PolicySource(**source.model_dump()) for source in item.sources]
        row.actions = [PolicyAction(**action.model_dump()) for action in item.actions]
        db.add(row)
        db.flush()
        counts["created"] += 1
    return counts


def snapshot(db: Session, row: PolicyVersion, reference_date: date):
    policy = db.get(Policy, row.policy_id)
    state = (
        "ended"
        if row.lifecycle == "ended"
        else "expired"
        if row.effective_until is not None and row.effective_until < reference_date
        else "active"
    )
    data = {
        field: getattr(row, field)
        for field in PolicyVersionInput.model_fields
        if hasattr(row, field)
    }
    data.update(
        policy_key=policy.policy_key,
        is_example=policy.is_example,
        sources=[
            PolicySourceInput(
                **{field: getattr(source, field) for field in PolicySourceInput.model_fields}
            )
            for source in row.sources
        ],
        actions=[
            PolicyActionSnapshot(
                id=action.id,
                **{
                    field: getattr(action, field)
                    for field in PolicyActionSnapshot.model_fields
                    if field != "id"
                },
            )
            for action in row.actions
        ],
    )
    return PolicySnapshot(
        **data,
        policy_id=policy.id,
        version_id=row.id,
        reference_date=reference_date,
        state=state,
    )


def get_policy_context(db: Session, policy_id: UUID, reference_date: date | None = None):
    reference_date = reference_date or today_kst()
    policy = db.get(Policy, policy_id)
    if policy is None or policy.is_example:
        raise AppError(404, "POLICY_NOT_FOUND", "정책을 찾을 수 없습니다.")
    row = repository.version_at(db, policy_id, reference_date)
    if row is None:
        raise AppError(404, "POLICY_NOT_EFFECTIVE", "기준일에 적용되는 정책이 없습니다.")
    return snapshot(db, row, reference_date)


def get_version_context(db: Session, version_id: UUID):
    row = repository.version_by_id(db, version_id)
    if row is None or db.get(Policy, row.policy_id).is_example:
        raise AppError(404, "POLICY_VERSION_NOT_FOUND", "정책 버전을 찾을 수 없습니다.")
    # Historical version references keep their original effective date.
    return snapshot(db, row, row.effective_from)
