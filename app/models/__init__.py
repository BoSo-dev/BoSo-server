"""Register domain models with the shared Alembic metadata."""

from app.modules.auth.models import AuthSession, RefreshToken, User
from app.modules.policies.models import Policy, PolicyAction, PolicySource, PolicyVersion
from app.modules.users.models import UserProfile, UserTransportCard, UserTransportMode

__all__ = [
    "AuthSession",
    "Policy",
    "PolicyAction",
    "PolicySource",
    "PolicyVersion",
    "RefreshToken",
    "User",
    "UserProfile",
    "UserTransportCard",
    "UserTransportMode",
]
