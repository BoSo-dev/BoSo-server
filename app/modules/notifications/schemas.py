from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator


class NotificationItem(BaseModel):
    id: UUID
    todo_id: UUID
    kind: Literal["new_todo", "due_soon"]
    title: str
    body: str
    due_date: date | None
    read_at: datetime | None
    created_at: datetime

    @field_validator("read_at", "created_at")
    @classmethod
    def utc_time(cls, value):
        if value is not None:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value


class NotificationPage(BaseModel):
    items: list[NotificationItem]
    total: int
    limit: int
    offset: int


class UnreadCount(BaseModel):
    count: int


class ReadResult(BaseModel):
    updated: int


class NotificationSyncResult(BaseModel):
    created: int
    todo_created: int
    todo_archived: int
