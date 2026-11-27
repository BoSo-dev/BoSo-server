from sqlalchemy import func, select, update

from app.modules.notifications.models import Notification


def owned(db, user_id, notification_id, *, lock=False):
    statement = select(Notification).where(
        Notification.user_id == user_id, Notification.id == notification_id
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement.execution_options(populate_existing=True))


def page(db, user_id, unread, limit, offset):
    predicates = [Notification.user_id == user_id]
    if unread is not None:
        predicates.append(
            Notification.read_at.is_(None) if unread else Notification.read_at.is_not(None)
        )
    total = db.scalar(select(func.count()).select_from(Notification).where(*predicates))
    rows = db.scalars(
        select(Notification)
        .where(*predicates)
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return rows, total


def event_keys(db, user_id):
    return set(db.scalars(select(Notification.event_key).where(Notification.user_id == user_id)))


def unread_count(db, user_id):
    return db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )


def mark_all_read(db, user_id, now):
    return db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    ).rowcount
