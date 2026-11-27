from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession, RefreshToken, User


def user_by_email(db: Session, email: str):
    return db.scalar(select(User).where(func.lower(User.email) == email))


def session_by_id(db: Session, session_id: UUID, *, lock: bool = False):
    query = select(AuthSession).where(AuthSession.id == session_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def token_by_hash(db: Session, token_hash: str):
    return db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .execution_options(populate_existing=True)
    )


def locked_refresh(db: Session, token_hash: str):
    # Read only the parent ID first. After acquiring its lock, re-read the token
    # so a waiter observes used_at committed by the first refresh request.
    session_id = db.scalar(
        select(RefreshToken.session_id).where(RefreshToken.token_hash == token_hash)
    )
    if session_id is None:
        return None, None
    session = session_by_id(db, session_id, lock=True)
    return session, token_by_hash(db, token_hash) if session is not None else None
