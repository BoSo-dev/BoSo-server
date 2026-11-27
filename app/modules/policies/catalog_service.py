from sqlalchemy import select

from app.core.errors import AppError
from app.modules.policies import repository
from app.modules.policies.models import Policy
from app.modules.policies.schemas import (
    EligibilityRules,
    PersonalizedPolicy,
    PersonalizedPolicyPage,
    PolicyActionSnapshot,
    PolicyCategory,
    PolicyChanges,
    PolicyDetail,
    PolicyPage,
    PolicySourceInput,
    PolicySources,
    PolicySummary,
)
from app.modules.policies.service import today_kst
from app.modules.todos.eligibility import evaluate_eligibility
from app.modules.users.service import get_personalization_context

CATEGORIES = (
    ("transport_card", "교통카드"),
    ("transport_fare", "교통요금"),
    ("transport_support", "교통비 지원"),
    ("transport_service", "교통서비스"),
)


def categories():
    return [PolicyCategory(code=code, label=label) for code, label in CATEGORIES]


def normalize_query(q):
    if q is None:
        return None
    q = q.strip()
    if not q:
        raise AppError(422, "INVALID_POLICY_SEARCH", "검색어를 입력해주세요.")
    return q


def summary(row, policy_key, today, *, current=True):
    state = (
        "superseded"
        if not current
        else "ended"
        if row.lifecycle == "ended"
        else "expired"
        if row.effective_until is not None and row.effective_until < today
        else "active"
    )
    return PolicySummary(
        policy_id=row.policy_id,
        policy_key=policy_key,
        version_id=row.id,
        version=row.version,
        title=row.title,
        category=row.category,
        summary=row.summary,
        state=state,
        is_current=current,
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        reviewed_on=row.reviewed_on,
    )


def list_policies(db, *, q=None, category=None, state="active", limit=20, offset=0):
    today = today_kst()
    rows, total = repository.catalog_page(
        db, today, q=normalize_query(q), category=category, state=state, limit=limit, offset=offset
    )
    return PolicyPage(
        items=[summary(row, key, today) for row, key in rows],
        total=total,
        limit=limit,
        offset=offset,
        reference_date=today,
    )


def require_history(db, policy_id, today):
    rows = repository.visible_history(db, policy_id, today)
    if not rows:
        raise AppError(404, "POLICY_NOT_FOUND", "정책을 찾을 수 없습니다.")
    return rows, db.scalar(select(Policy.policy_key).where(Policy.id == policy_id))


def detail(row, policy_key, today, current_id):
    return PolicyDetail(
        **summary(row, policy_key, today, current=row.id == current_id).model_dump(),
        content=row.content,
        lifecycle=row.lifecycle,
        change_summary=row.change_summary,
        eligibility=EligibilityRules.model_validate(row.eligibility),
        sources=[
            PolicySourceInput(
                **{field: getattr(source, field) for field in PolicySourceInput.model_fields}
            )
            for source in row.sources
        ],
        actions=[
            PolicyActionSnapshot(
                **{field: getattr(action, field) for field in PolicyActionSnapshot.model_fields}
            )
            for action in row.actions
        ],
    )


def read_policy(db, policy_id, version=None):
    today = today_kst()
    rows, key = require_history(db, policy_id, today)
    row = (
        rows[0] if version is None else next((row for row in rows if row.version == version), None)
    )
    if row is None:
        raise AppError(404, "POLICY_VERSION_NOT_FOUND", "정책 버전을 찾을 수 없습니다.")
    return detail(row, key, today, rows[0].id)


def history_page(db, policy_id, limit=20, offset=0):
    today = today_kst()
    rows, key = require_history(db, policy_id, today)
    return PolicyPage(
        items=[
            summary(row, key, today, current=row.id == rows[0].id)
            for row in rows[offset : offset + limit]
        ],
        total=len(rows),
        limit=limit,
        offset=offset,
        reference_date=today,
    )


def sources(db, policy_id):
    policy = read_policy(db, policy_id)
    return PolicySources(policy_id=policy_id, version_id=policy.version_id, sources=policy.sources)


def changes(db, policy_id, from_version=None, to_version=None):
    today = today_kst()
    rows, key = require_history(db, policy_id, today)
    after = (
        rows[0]
        if to_version is None
        else next((row for row in rows if row.version == to_version), None)
    )
    before = (
        next((row for row in rows if row.version < after.version), None)
        if after is not None and from_version is None
        else next((row for row in rows if row.version == from_version), None)
    )
    if after is None or (from_version is not None and before is None):
        raise AppError(404, "POLICY_VERSION_NOT_FOUND", "정책 버전을 찾을 수 없습니다.")
    if before is not None and before.version >= after.version:
        raise AppError(
            422, "INVALID_POLICY_COMPARISON", "변경 전 버전은 변경 후 버전보다 작아야 합니다."
        )
    old = detail(before, key, today, rows[0].id) if before is not None else None
    new = detail(after, key, today, rows[0].id)

    def business_values(value):
        data = value.model_dump(
            mode="json",
            include={
                "title",
                "category",
                "summary",
                "content",
                "effective_from",
                "effective_until",
                "eligibility",
                "sources",
                "actions",
                "lifecycle",
            },
        )
        data["actions"] = [
            {key: item for key, item in action.items() if key != "id"} for action in data["actions"]
        ]
        return data

    after_values = business_values(new)
    before_values = business_values(old) if old is not None else {}
    return PolicyChanges(
        before=old,
        after=new,
        changed_fields=[
            field for field, value in after_values.items() if before_values.get(field) != value
        ],
    )


def for_user(
    db, user_id, *, q=None, category=None, state="active", eligibility=None, limit=20, offset=0
):
    today = today_kst()
    profile = get_personalization_context(db, user_id, reference_date=today)
    statement = repository.catalog_statement(
        today, q=normalize_query(q), category=category, state=state
    )
    items, total = [], 0
    # Stream candidates so exact eligibility filtering does not retain the full catalog.
    for row, key in db.execute(statement.execution_options(yield_per=200)):
        result = evaluate_eligibility(EligibilityRules.model_validate(row.eligibility), profile)
        current = summary(row, key, today)
        result_state = result.state if current.state == "active" else "not_eligible"
        reasons = result.reasons if current.state == "active" else ["policy_inactive"]
        if eligibility is not None and result_state != eligibility:
            continue
        if offset <= total < offset + limit:
            items.append(
                PersonalizedPolicy(
                    **current.model_dump(),
                    eligibility_state=result_state,
                    eligibility_reasons=reasons,
                )
            )
        total += 1
    return PersonalizedPolicyPage(
        items=items, total=total, limit=limit, offset=offset, reference_date=today
    )
