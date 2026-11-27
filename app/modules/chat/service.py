import hashlib
import json
import re
from collections import OrderedDict
from datetime import UTC, datetime
from threading import Lock
from time import monotonic

from app.core.errors import AppError
from app.modules.chat import client, repository
from app.modules.chat.config import get_chat_settings
from app.modules.chat.models import ChatConversation, ChatTurn
from app.modules.chat.schemas import (
    Citation,
    ConversationItem,
    ConversationPage,
    TurnItem,
    TurnPage,
)
from app.modules.policies.service import get_policy_context, today_kst
from app.modules.todos.eligibility import evaluate_eligibility
from app.modules.todos.schemas import EligibilityResult
from app.modules.todos.service import related_todos
from app.modules.users.service import get_personalization_context

FALLBACK = "확인된 정책 근거가 부족합니다. 정책 이름이나 필요한 조건을 구체적으로 알려주세요. 최신 내용은 공식 안내에서 확인해주세요."


class ChatLimiter:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, user_id):
        now = monotonic()
        with self.lock:
            start, count = self.entries.pop(user_id, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self.entries[user_id] = (start, count + 1)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)
            if count >= 10:
                raise AppError(429, "CHAT_RATE_LIMITED", "잠시 후 다시 질문해주세요.")


limiter = ChatLimiter()


def assess(context, profile):
    if context.state != "active":
        return EligibilityResult(state="not_eligible", reasons=["policy_inactive"])
    return evaluate_eligibility(context.eligibility, profile)


def conversation_item(row):
    return ConversationItem(**{name: getattr(row, name) for name in ConversationItem.model_fields})


def require_conversation(db, user_id, conversation_id, *, lock=False):
    row = repository.conversation(db, user_id, conversation_id, lock=lock)
    if row is None:
        raise AppError(404, "CHAT_NOT_FOUND", "대화를 찾을 수 없습니다.")
    return row


def create_conversation(db, user_id, body):
    row = ChatConversation(user_id=user_id, title=body.title)
    db.add(row)
    db.flush()
    return conversation_item(row)


def list_conversations(db, user_id, limit=20, offset=0):
    rows, total = repository.conversations(db, user_id, limit, offset)
    return ConversationPage(
        items=[conversation_item(row) for row in rows], total=total, limit=limit, offset=offset
    )


def turn_item(db, user_id, row):
    sources = [Citation.model_validate(value) for value in row.sources]
    return TurnItem(
        **{
            field: getattr(row, field)
            for field in TurnItem.model_fields
            if field not in {"related_todos", "sources"}
        },
        sources=sources,
        related_todos=related_todos(db, user_id, {source.policy_id for source in sources}),
    )


def list_turns(db, user_id, conversation_id, limit=20, offset=0):
    require_conversation(db, user_id, conversation_id)
    return TurnPage(
        items=[
            turn_item(db, user_id, row)
            for row in repository.turns(db, conversation_id, limit, offset)
        ],
        total=repository.turn_count(db, conversation_id),
        limit=limit,
        offset=offset,
    )


def send_message(db, user_id, conversation_id, body):
    conversation = require_conversation(db, user_id, conversation_id, lock=True)
    digest = hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    existing = repository.turn_by_request(db, conversation_id, body.request_id)
    if existing:
        if existing.request_hash != digest:
            raise AppError(409, "CHAT_REQUEST_CONFLICT", "같은 요청 ID의 내용이 다릅니다.")
        return turn_item(db, user_id, existing)
    history = repository.turns(db, conversation_id, 3, newest=True)
    policy_ids = body.policy_ids or repository.find_policies(
        db, re.findall(r"[가-힣a-zA-Z0-9_-]{2,40}", body.question)[:8]
    )
    if not policy_ids and history:
        policy_ids = sorted(
            {Citation.model_validate(source).policy_id for source in history[0].sources}, key=str
        )[:5]
    contexts = []
    today = today_kst()
    for policy_id in policy_ids:
        try:
            contexts.append(get_policy_context(db, policy_id, today))
        except AppError as exc:
            if body.policy_ids:
                raise
            if exc.status != 404:
                raise
    answer, sources, needs_more_info, external_used = FALLBACK, [], True, False
    if contexts:
        profile = get_personalization_context(db, user_id, reference_date=today)
        allowed = {}
        for context in contexts:
            for source in context.sources:
                citation = Citation(
                    policy_id=context.policy_id,
                    version_id=context.version_id,
                    source_key=source.source_key,
                    title=source.title,
                    url=source.url,
                )
                allowed[(context.version_id, source.source_key)] = citation
        payload = {
            "question": body.question,
            "conversation": [
                {"question": row.question, "answer": row.answer} for row in reversed(history)
            ],
            "policies": [
                {
                    "version_id": str(context.version_id),
                    "title": context.title,
                    "summary": context.summary,
                    "content": context.content[:2500],
                    "state": context.state,
                    "effective_from": str(context.effective_from),
                    "effective_until": str(context.effective_until)
                    if context.effective_until
                    else None,
                    "assessment": assess(context, profile).model_dump(),
                    "actions": [
                        {
                            "title": action.title,
                            "description": action.description[:500],
                            "due_date": str(action.due_date) if action.due_date else None,
                        }
                        for action in context.actions[:10]
                    ],
                    "source_keys": [source.source_key for source in context.sources],
                }
                for context in contexts
            ],
        }
        settings = get_chat_settings()
        if not settings.gemini_api_key or not settings.gemini_model:
            raise AppError(503, "CHAT_NOT_CONFIGURED", "상담 기능 설정을 확인해주세요.")
        limiter.check(user_id)
        reply = client.generate(settings, payload)
        external_used = True
        if reply.references and all(
            (ref.version_id, ref.source_key) in allowed for ref in reply.references
        ):
            answer = reply.answer
            sources = list(
                {
                    (ref.version_id, ref.source_key): allowed[(ref.version_id, ref.source_key)]
                    for ref in reply.references
                }.values()
            )
            needs_more_info = reply.needs_more_info or any(
                assess(context, profile).state == "unknown" for context in contexts
            )
    row = ChatTurn(
        conversation_id=conversation_id,
        request_id=body.request_id,
        request_hash=digest,
        turn_number=repository.turn_count(db, conversation_id) + 1,
        question=body.question,
        answer=answer,
        sources=[source.model_dump(mode="json") for source in sources],
        needs_more_info=needs_more_info,
        external_used=external_used,
    )
    db.add(row)
    conversation.updated_at = datetime.now(UTC)
    db.flush()
    return turn_item(db, user_id, row)
