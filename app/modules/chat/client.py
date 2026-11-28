"""BoSo AI 패키지 호출. 기존 ModelReply/AppError 계약을 유지한다."""

from boso_ai.backend import generate_chat_reply

from app.core.errors import AppError
from app.modules.chat.schemas import ModelReply


def generate(settings, payload):
    reply = generate_chat_reply(settings, payload, error_factory=AppError)
    return ModelReply.model_validate(reply.model_dump(mode="json"))
