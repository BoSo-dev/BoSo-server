"""Register domain models with the shared Alembic metadata."""

from app.modules.auth.models import AuthSession, RefreshToken, User

__all__ = ["AuthSession", "RefreshToken", "User"]
