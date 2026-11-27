import hashlib
from datetime import UTC, datetime

from app.core.errors import AppError
from app.modules.notifications import repository
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import (
    NotificationItem,
    NotificationPage,
    NotificationSyncResult,
)
from app.modules.policies.service import today_kst
from app.modules.todos import service as todos


def item(row):
    return NotificationItem(**{name: getattr(row, name) for name in NotificationItem.model_fields})


def list_notifications(db, user_id, unread=None, limit=20, offset=0):
    rows, total = repository.page(db, user_id, unread, limit, offset)
    return NotificationPage(
        items=[item(row) for row in rows], total=total, limit=limit, offset=offset
    )


def mark_read(db, user_id, notification_id):
    row = repository.owned(db, user_id, notification_id, lock=True)
    if row is None:
        raise AppError(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        db.flush()
    return item(row)


def unread_count(db, user_id):
    return repository.unread_count(db, user_id)


def mark_all_read(db, user_id):
    return repository.mark_all_read(db, user_id, datetime.now(UTC))


def synchronize(db, user_id):
    # The To-Do service locks the user and refreshes policy/profile eligibility
    # before notifications are created in this same transaction.
    today = today_kst()
    result = todos.synchronize(db, user_id, reference_date=today)
    known = repository.event_keys(db, user_id)
    count = 0
    for todo in todos.pending_todos(db, user_id):
        events = [("new_todo", None)]
        if todo.due_date is not None and 0 <= (todo.due_date - today).days <= 3:
            events.append(("due_soon", todo.due_date))
        for kind, deadline in events:
            key = hashlib.sha256(f"{kind}:{todo.id}:{deadline or ''}".encode()).hexdigest()
            if key in known:
                continue
            known.add(key)
            title = "새 할 일이 있어요" if kind == "new_todo" else "할 일의 마감이 가까워요"
            body = (
                todo.title if deadline is None else f"{todo.title} · 마감일 {deadline.isoformat()}"
            )
            db.add(
                Notification(
                    user_id=user_id,
                    todo_id=todo.id,
                    event_key=key,
                    kind=kind,
                    title=title,
                    body=body,
                    due_date=deadline,
                )
            )
            count += 1
    db.flush()
    return NotificationSyncResult(
        created=count, todo_created=result.created, todo_archived=result.archived
    )
