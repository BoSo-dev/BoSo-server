from uuid import UUID

from fastapi import APIRouter, Query

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import CurrentUser
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    NotificationItem,
    NotificationPage,
    NotificationSyncResult,
    ReadResult,
    UnreadCount,
)
from app.modules.todos.schemas import EmptyRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/sync", response_model=NotificationSyncResult)
def sync_notifications(body: EmptyRequest, db: DbSession, user: CurrentUser):
    return service.synchronize(db, user.id)


@router.get("", response_model=NotificationPage)
def list_notifications(
    db: DbSession,
    user: CurrentUser,
    unread: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return service.list_notifications(db, user.id, unread, limit, offset)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(db: DbSession, user: CurrentUser):
    return UnreadCount(count=service.unread_count(db, user.id))


@router.post("/read-all", response_model=ReadResult)
def read_all(body: EmptyRequest, db: DbSession, user: CurrentUser):
    return ReadResult(updated=service.mark_all_read(db, user.id))


@router.post("/{notification_id}/read", response_model=NotificationItem)
def read_notification(notification_id: UUID, body: EmptyRequest, db: DbSession, user: CurrentUser):
    return service.mark_read(db, user.id, notification_id)
