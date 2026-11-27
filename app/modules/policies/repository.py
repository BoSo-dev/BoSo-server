from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.policies.models import Policy, PolicyVersion


def lock_policy(db: Session, policy_key: str, is_example: bool):
    # Upsert first, then lock: two first-time imports must share the same row.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif db.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ValueError("Unsupported policy database")
    db.execute(
        insert(Policy)
        .values(policy_key=policy_key, is_example=is_example)
        .on_conflict_do_nothing(index_elements=[Policy.policy_key])
    )
    return db.scalar(select(Policy).where(Policy.policy_key == policy_key).with_for_update())


def versions(db: Session, policy_id):
    return db.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy_id)
        .order_by(PolicyVersion.version.desc())
    ).all()


def version_at(db: Session, policy_id, reference_date: date):
    return db.scalar(
        select(PolicyVersion)
        .where(
            PolicyVersion.policy_id == policy_id,
            PolicyVersion.effective_from <= reference_date,
        )
        .order_by(PolicyVersion.effective_from.desc(), PolicyVersion.version.desc())
        .options(selectinload(PolicyVersion.sources), selectinload(PolicyVersion.actions))
        .limit(1)
    )


def version_by_id(db: Session, version_id):
    return db.scalar(
        select(PolicyVersion)
        .where(PolicyVersion.id == version_id)
        .options(selectinload(PolicyVersion.sources), selectinload(PolicyVersion.actions))
    )
