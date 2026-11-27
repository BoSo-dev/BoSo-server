"""Register domain models with the shared Alembic metadata."""

from app.modules.auth.models import AuthSession, RefreshToken, User
from app.modules.users.models import UserProfile, UserTransportCard, UserTransportMode

__all__ = [
    "AuthSession",
    "RefreshToken",
    "User",
    "UserProfile",
    "UserTransportCard",
    "UserTransportMode",
]
