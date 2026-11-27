"""Register domain models with the shared Alembic metadata."""

from app.modules.auth.models import AuthSession, RefreshToken, User
from app.modules.chat.models import ChatConversation, ChatTurn
from app.modules.policies.models import Policy, PolicyAction, PolicySource, PolicyVersion
from app.modules.todos.models import UserTodo
from app.modules.users.models import UserProfile, UserTransportCard, UserTransportMode

__all__ = [
    "AuthSession",
    "ChatConversation",
    "ChatTurn",
    "Policy",
    "PolicyAction",
    "PolicySource",
    "PolicyVersion",
    "RefreshToken",
    "User",
    "UserTodo",
    "UserProfile",
    "UserTransportCard",
    "UserTransportMode",
]
