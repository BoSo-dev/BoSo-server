from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.auth import repository, security
from app.modules.auth.models import AuthSession, RefreshToken, User


@dataclass
class Grant:
    user_id: UUID
    session_id: UUID
    refresh_token: str = field(repr=False)
    expires_at: datetime


def unauthorized():
    return AppError(401, "AUTH_REQUIRED", "유효한 인증이 필요합니다.")


def signup(db: Session, email: str, password: str):
    encoded = security.password_hasher.hash(password)
    if repository.user_by_email(db, email):
        raise AppError(409, "EMAIL_IN_USE", "이미 등록된 이메일입니다.")
    user = User(email=email, password_hash=encoded)
    try:
        db.add(user)
        db.flush()
    except IntegrityError:
        db.rollback()
        if repository.user_by_email(db, email):
            raise AppError(409, "EMAIL_IN_USE", "이미 등록된 이메일입니다.") from None
        raise
    return user


def login(db: Session, email: str, password: str):
    user = repository.user_by_email(db, email)
    encoded = user.password_hash if user is not None else security.dummy_password_hash()
    valid = security.verify_password(encoded, password)
    if not valid or user is None or not user.is_active:
        raise AppError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호를 확인해주세요.")
    if security.password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = security.password_hasher.hash(password)
    now = security.now_utc()
    session = AuthSession(
        user_id=user.id, created_at=now, expires_at=now + security.SESSION_LIFETIME
    )
    db.add(session)
    db.flush()
    return add_refresh(db, session, now)


def add_refresh(db: Session, session: AuthSession, now: datetime):
    raw = security.new_refresh_token()
    db.add(
        RefreshToken(
            session_id=session.id,
            token_hash=security.refresh_hash(raw),
            created_at=now,
            expires_at=session.expires_at,
        )
    )
    db.flush()
    return Grant(session.user_id, session.id, raw, security.as_utc(session.expires_at))


def active_session(db: Session, session: AuthSession | None):
    if (
        session is None
        or session.revoked_at
        or security.as_utc(session.expires_at) <= security.now_utc()
    ):
        return False
    user = db.get(User, session.user_id, populate_existing=True)
    return user is not None and user.is_active


def authenticated_user(db: Session, settings: Settings, token: str):
    user_id, session_id = security.decode_access(settings, token)
    session = repository.session_by_id(db, session_id)
    if not active_session(db, session) or session.user_id != user_id:
        raise unauthorized()
    return db.get(User, user_id)


def cookie_session(db: Session, raw: str | None):
    if not security.valid_refresh_format(raw):
        raise unauthorized()
    session, token = repository.locked_refresh(db, security.refresh_hash(raw))
    if session is None or token is None:
        raise unauthorized()
    return session, token


def refresh(
    db: Session, settings: Settings, raw: str | None, cookie: str | None, header: str | None
):
    session, token = cookie_session(db, raw)
    security.verify_csrf(settings, session.id, cookie, header)
    if not active_session(db, session) or security.as_utc(token.expires_at) <= security.now_utc():
        return None
    now = security.now_utc()
    if token.used_at is not None:
        session.revoked_at = now
        session.revocation_reason = "refresh_reuse"
        db.flush()
        # Return an outcome, NOT an exception: get_db must commit this revocation
        # before the router's 401 response is sent, not roll it back.
        return None
    token.used_at = now
    db.flush()  # Release partial-unique slot before inserting its replacement.
    return add_refresh(db, session, now)


def csrf_bootstrap(db: Session, raw: str | None):
    session, token = cookie_session(db, raw)
    if (
        not active_session(db, session)
        or token.used_at is not None
        or security.as_utc(token.expires_at) <= security.now_utc()
    ):
        raise unauthorized()
    return session


def logout(
    db: Session, settings: Settings, raw: str | None, cookie: str | None, header: str | None
):
    if raw is None:
        return
    session, _ = cookie_session(db, raw)
    security.verify_csrf(settings, session.id, cookie, header)
    if session.revoked_at is None:
        session.revoked_at = security.now_utc()
        session.revocation_reason = "logout"
        db.flush()
