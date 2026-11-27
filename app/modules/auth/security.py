import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.errors import AppError

ACCESS_LIFETIME = timedelta(minutes=15)
SESSION_LIFETIME = timedelta(days=7)
password_hasher = PasswordHasher()  # Argon2id; library's RFC 9106 low-memory profile.


def now_utc():
    return datetime.now(UTC)


def as_utc(value: datetime):
    # SQLite loses offsets; production TIMESTAMPTZ already has a timezone.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def require_auth_settings(settings: Settings):
    if settings.auth_jwt_key is None or settings.auth_csrf_key is None:
        raise AppError(503, "AUTH_NOT_CONFIGURED", "인증 설정이 준비되지 않았습니다.")
    return settings


@lru_cache(maxsize=1)
def dummy_password_hash():
    return password_hasher.hash(secrets.token_urlsafe(32))


def verify_password(encoded: str, password: str):
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def new_refresh_token():
    return secrets.token_urlsafe(32)


def refresh_hash(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def valid_refresh_format(token: str | None):
    return token is not None and re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is not None


def issue_access(settings: Settings, user_id: UUID, session_id: UUID, expires_at: datetime):
    now = now_utc()
    expiry = min(now + ACCESS_LIFETIME, as_utc(expires_at))
    claims = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "type": "access",
    }
    return jwt.encode(claims, settings.auth_jwt_key.get_secret_value(), algorithm="HS256"), max(
        0, claims["exp"] - claims["iat"]
    )


def decode_access(settings: Settings, token: str):
    try:
        if len(token) > 4096:
            raise ValueError
        claims = jwt.decode(
            token,
            settings.auth_jwt_key.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            options={
                "require": ["sub", "sid", "iat", "exp", "iss", "aud", "type"],
                "strict_aud": True,
            },
        )
        if (
            claims["type"] != "access"
            or type(claims["iat"]) is not int
            or type(claims["exp"]) is not int
            or not 0 < claims["exp"] - claims["iat"] <= int(ACCESS_LIFETIME.total_seconds())
        ):
            raise ValueError
        return UUID(claims["sub"]), UUID(claims["sid"])
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise AppError(401, "AUTH_REQUIRED", "유효한 인증이 필요합니다.") from None


def new_csrf(settings: Settings, session_id: UUID):
    nonce = secrets.token_urlsafe(32)
    message = f"boso-csrf:{session_id}:{nonce}".encode()
    signature = hmac.new(
        settings.auth_csrf_key.get_secret_value().encode(), message, hashlib.sha256
    ).hexdigest()
    return f"{nonce}.{signature}"


def verify_csrf(settings: Settings, session_id: UUID, cookie: str | None, header: str | None):
    if (
        not cookie
        or not header
        or re.fullmatch(r"[A-Za-z0-9_-]{43}\.[0-9a-f]{64}", cookie) is None
        or re.fullmatch(r"[A-Za-z0-9_-]{43}\.[0-9a-f]{64}", header) is None
        or not hmac.compare_digest(cookie, header)
    ):
        raise AppError(403, "CSRF_FAILED", "요청 보안 정보를 확인해주세요.")
    nonce, signature = cookie.split(".")
    message = f"boso-csrf:{session_id}:{nonce}".encode()
    expected = hmac.new(
        settings.auth_csrf_key.get_secret_value().encode(), message, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AppError(403, "CSRF_FAILED", "요청 보안 정보를 확인해주세요.")
