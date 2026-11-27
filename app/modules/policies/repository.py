from datetime import date

from sqlalchemy import case, func, or_, select
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


def catalog_statement(reference_date, *, q=None, category=None, state="active"):
    ranked = (
        select(
            PolicyVersion.id.label("version_id"),
            func.row_number()
            .over(
                partition_by=PolicyVersion.policy_id,
                order_by=(PolicyVersion.effective_from.desc(), PolicyVersion.version.desc()),
            )
            .label("position"),
        )
        .join(Policy, Policy.id == PolicyVersion.policy_id)
        .where(Policy.is_example.is_(False), PolicyVersion.effective_from <= reference_date)
        .subquery()
    )
    statement = (
        select(PolicyVersion, Policy.policy_key)
        .join(Policy, Policy.id == PolicyVersion.policy_id)
        .join(ranked, ranked.c.version_id == PolicyVersion.id)
        .where(ranked.c.position == 1)
    )
    # Select the latest applicable version BEFORE search/category/state filtering.
    # A retired or renamed version must never resurrect an older match.
    if q is not None:
        statement = statement.where(
            or_(
                PolicyVersion.title.icontains(q, autoescape=True),
                PolicyVersion.summary.icontains(q, autoescape=True),
                PolicyVersion.content.icontains(q, autoescape=True),
            )
        )
    if category is not None:
        statement = statement.where(PolicyVersion.category == category)
    if state != "all":
        actual_state = case(
            (PolicyVersion.lifecycle == "ended", "ended"),
            (PolicyVersion.effective_until < reference_date, "expired"),
            else_="active",
        )
        statement = statement.where(actual_state == state)
    return statement.order_by(PolicyVersion.effective_from.desc(), Policy.policy_key)


def catalog_page(db, reference_date, *, q=None, category=None, state="active", limit=20, offset=0):
    statement = catalog_statement(reference_date, q=q, category=category, state=state)
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    return db.execute(statement.limit(limit).offset(offset)).all(), total


def visible_history(db, policy_id, reference_date):
    return db.scalars(
        select(PolicyVersion)
        .join(Policy, Policy.id == PolicyVersion.policy_id)
        .where(
            Policy.id == policy_id,
            Policy.is_example.is_(False),
            PolicyVersion.effective_from <= reference_date,
        )
        .order_by(PolicyVersion.version.desc())
    ).all()
