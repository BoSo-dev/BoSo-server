from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.todos.schemas import TodoItem


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class ConversationCreate(ChatInput):
    title: str = Field(default="정책 상담", min_length=1, max_length=100)


class TurnRequest(ChatInput):
    request_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    policy_ids: list[UUID] = Field(default_factory=list, max_length=5)

    @field_validator("policy_ids")
    @classmethod
    def unique_policies(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate policy IDs")
        return sorted(value, key=str)


class Reference(ChatInput):
    version_id: UUID
    source_key: str = Field(min_length=1, max_length=64)


class ModelReply(ChatInput):
    answer: str = Field(min_length=1, max_length=4000)
    references: list[Reference] = Field(max_length=10)
    needs_more_info: bool = Field(strict=True)


class Citation(Reference):
    policy_id: UUID
    title: str
    url: str


class ConversationItem(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_time(cls, value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ConversationPage(BaseModel):
    items: list[ConversationItem]
    total: int
    limit: int
    offset: int


class TurnItem(BaseModel):
    id: UUID
    request_id: UUID
    turn_number: int
    question: str
    answer: str
    sources: list[Citation]
    needs_more_info: bool
    external_used: bool
    created_at: datetime
    related_todos: list[TodoItem]

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class TurnPage(BaseModel):
    items: list[TurnItem]
    total: int
    limit: int
    offset: int
