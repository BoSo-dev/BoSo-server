from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import Base, make_engine
from app.models import AuthSession, RefreshToken, User

CREATED = datetime(2026, 10, 30, tzinfo=UTC)
EXPIRES = CREATED + timedelta(days=7)


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'auth-models.db'}")
    # Only this disposable SQLite database; never the application engine or .env.
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def user_graph():
    user = User(email="member@example.invalid", password_hash="test-only-hash")
    session = AuthSession(user=user, created_at=CREATED, expires_at=EXPIRES)
    token = RefreshToken(
        session=session, token_hash="a" * 64, created_at=CREATED, expires_at=EXPIRES
    )
    return user, session, token


def test_model_relationships_and_defaults(db):
    user, session, token = user_graph()
    db.add(user)
    db.commit()
    db.expire_all()
    assert isinstance(user.id, UUID)
    assert isinstance(session.id, UUID)
    assert isinstance(token.id, UUID)
    assert user.is_active is True
    assert user.created_at is not None and user.updated_at is not None
    assert user.sessions == [session]
    assert session.user is user
    assert session.refresh_tokens == [token]
    assert token.session is session
    assert session.revoked_at is None and session.revocation_reason is None
    assert token.used_at is None


def test_models_are_registered_and_timestamps_are_timezone_aware():
    assert {"users", "auth_sessions", "refresh_tokens"} <= set(Base.metadata.tables)
    for model in (User, AuthSession, RefreshToken):
        for column in model.__table__.columns:
            if column.name.endswith("_at"):
                assert column.type.timezone is True
    assert RefreshToken.__table__.c.token_hash.type.length == 64


def test_email_uniqueness_is_case_insensitive(db):
    db.add(User(email="Member@example.invalid", password_hash="test-only-hash"))
    db.commit()
    db.add(User(email="member@example.invalid", password_hash="test-only-hash"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    "email", [None, "", " ", " member@example.invalid", "member@example.invalid "]
)
def test_email_cannot_be_null_empty_or_untrimmed(email, db):
    db.add(User(email=email, password_hash="test-only-hash"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("password_hash", [None, ""])
def test_password_hash_is_required(password_hash, db):
    db.add(User(email="member@example.invalid", password_hash=password_hash))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("length", [0, 1, 63, 65])
def test_token_hash_length_is_exactly_64(length, db):
    user, _, token = user_graph()
    token.token_hash = "a" * length
    db.add(user)
    with pytest.raises(IntegrityError):
        db.commit()


def test_token_hash_uniqueness_applies_across_sessions(db):
    user, session, token = user_graph()
    other = AuthSession(user=user, created_at=CREATED, expires_at=EXPIRES)
    RefreshToken(session=other, token_hash=token.token_hash, created_at=CREATED, expires_at=EXPIRES)
    db.add(user)
    with pytest.raises(IntegrityError):
        db.commit()


def test_only_one_unconsumed_token_per_session(db):
    user, session, _ = user_graph()
    db.add(user)
    db.commit()
    db.add(
        RefreshToken(session=session, token_hash="b" * 64, created_at=CREATED, expires_at=EXPIRES)
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_token_can_be_rotated_while_preserving_used_history(db):
    user, session, token = user_graph()
    db.add(user)
    db.commit()
    token.used_at = CREATED + timedelta(minutes=15)
    db.flush()  # Release the partial UNIQUE index slot before inserting replacement.
    db.add(
        RefreshToken(session=session, token_hash="b" * 64, created_at=CREATED, expires_at=EXPIRES)
    )
    db.commit()
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 2
    assert (
        db.scalar(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.used_at.is_(None))
        )
        == 1
    )


@pytest.mark.parametrize("model", [AuthSession, RefreshToken])
@pytest.mark.parametrize("offset", [0, -1])
def test_expiry_must_be_after_creation(model, offset, db):
    user, session, token = user_graph()
    target = session if model is AuthSession else token
    target.expires_at = CREATED + timedelta(seconds=offset)
    db.add(user)
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    ("revoked_at", "reason"),
    [
        (None, "logout"),
        (CREATED, None),
        (CREATED, "unknown"),
        (CREATED - timedelta(seconds=1), "logout"),
    ],
)
def test_revocation_state_must_be_consistent(revoked_at, reason, db):
    user, session, _ = user_graph()
    session.revoked_at = revoked_at
    session.revocation_reason = reason
    db.add(user)
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("reason", ["logout", "refresh_reuse", "user_disabled"])
def test_valid_revocation_reasons(reason, db):
    user, session, _ = user_graph()
    session.revoked_at = CREATED
    session.revocation_reason = reason
    db.add(user)
    db.commit()


def test_token_cannot_be_used_before_creation(db):
    user, _, token = user_graph()
    token.used_at = CREATED - timedelta(seconds=1)
    db.add(user)
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("model", [AuthSession, RefreshToken])
def test_foreign_keys_reject_missing_parent(model, db):
    row = (
        AuthSession(user_id=uuid4(), created_at=CREATED, expires_at=EXPIRES)
        if model is AuthSession
        else RefreshToken(
            session_id=uuid4(), token_hash="a" * 64, created_at=CREATED, expires_at=EXPIRES
        )
    )
    db.add(row)
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("parent", [User, AuthSession])
def test_database_delete_cascades_without_orm_loading_children(parent, db):
    user, session, _ = user_graph()
    db.add(user)
    db.commit()
    parent_id = user.id if parent is User else session.id
    db.expunge_all()
    db.execute(delete(parent).where(parent.id == parent_id))
    db.commit()
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 0
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert db.scalar(select(func.count()).select_from(User)) == (0 if parent is User else 1)


def test_partial_index_and_fk_delete_rules_are_present(db):
    inspector = inspect(db.get_bind())
    index = next(
        i
        for i in inspector.get_indexes("refresh_tokens")
        if i["name"] == "uq_refresh_tokens_unconsumed_session"
    )
    assert index["unique"]
    assert "used_at IS NULL" in str(index["dialect_options"]["sqlite_where"])
    for table in ("auth_sessions", "refresh_tokens"):
        assert inspector.get_foreign_keys(table)[0]["options"]["ondelete"] == "CASCADE"
