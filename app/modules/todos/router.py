from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import CurrentUser
from app.modules.todos import service
from app.modules.todos.schemas import (
    EmptyRequest,
    TodoItem,
    TodoPage,
    TodoPatch,
    TodoSummary,
    TodoSyncResult,
)

router = APIRouter(prefix="/todos", tags=["todos"])


@router.post("/sync", response_model=TodoSyncResult)
def sync_todos(body: EmptyRequest, db: DbSession, user: CurrentUser):
    return service.synchronize(db, user.id)


@router.get("", response_model=TodoPage)
def list_todos(
    db: DbSession,
    user: CurrentUser,
    status: Literal["pending", "completed", "archived", "all"] = "pending",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return service.list_todos(db, user.id, status, limit, offset)


@router.get("/summary", response_model=TodoSummary)
def summary(db: DbSession, user: CurrentUser):
    return service.summary(db, user.id)


@router.get("/{todo_id}", response_model=TodoItem)
def read_todo(todo_id: UUID, db: DbSession, user: CurrentUser):
    return service.read_todo(db, user.id, todo_id)


@router.patch("/{todo_id}", response_model=TodoItem)
def change_completion(todo_id: UUID, body: TodoPatch, db: DbSession, user: CurrentUser):
    return service.change_completion(db, user.id, todo_id, body.completed)
