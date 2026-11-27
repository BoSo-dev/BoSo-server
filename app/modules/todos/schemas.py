from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TodoPatch(EmptyRequest):
    completed: bool = Field(strict=True)


class EligibilityResult(BaseModel):
    state: Literal["eligible", "not_eligible", "unknown"]
    reasons: list[str]


class TodoItem(BaseModel):
    id: UUID
    policy_id: UUID
    policy_version_id: UUID
    action_id: UUID
    action_key: str
    title: str
    description: str
    due_date: date | None
    status: Literal["pending", "completed", "archived"]
    archived_reason: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_overdue: bool

    @field_validator("completed_at", "created_at", "updated_at")
    @classmethod
    def utc_time(cls, value):
        if value is not None:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value


class TodoPage(BaseModel):
    items: list[TodoItem]
    total: int
    limit: int
    offset: int


class TodoSummary(BaseModel):
    pending: int
    completed: int
    archived: int
    overdue: int


class PolicyAssessment(BaseModel):
    policy_id: UUID
    result: EligibilityResult


class TodoSyncResult(BaseModel):
    created: int
    updated: int
    archived: int
    assessments: list[PolicyAssessment]
