from uuid import UUID

from fastapi import APIRouter, Query

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import CurrentUser
from app.modules.chat import service
from app.modules.chat.schemas import (
    ConversationCreate,
    ConversationItem,
    ConversationPage,
    TurnItem,
    TurnPage,
    TurnRequest,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/conversations", response_model=ConversationItem, status_code=201)
def create_conversation(body: ConversationCreate, db: DbSession, user: CurrentUser):
    return service.create_conversation(db, user.id, body)


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return service.list_conversations(db, user.id, limit, offset)


@router.get("/conversations/{conversation_id}/messages", response_model=TurnPage)
def list_messages(
    conversation_id: UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return service.list_turns(db, user.id, conversation_id, limit, offset)


@router.post("/conversations/{conversation_id}/messages", response_model=TurnItem, status_code=201)
def send_message(conversation_id: UUID, body: TurnRequest, db: DbSession, user: CurrentUser):
    return service.send_message(db, user.id, conversation_id, body)
