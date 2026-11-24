from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth_api import build_client, configure_auth_test, login, me, post, register
from test_auth_migrations import migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database

from alembic import command
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AuthSession, RefreshToken
from app.modules.auth import repository, security, service


@pytest.fixture
def migrated_database(postgres_database, monkeypatch):
    url, engine, _ = postgres_database
    # postgres_database already rejects remote/non-test URLs and creates only
    # a generated disposable database; never use the real .env as a fallback.
    command.upgrade(migration_config(monkeypatch, url), "head")
    configure_auth_test(monkeypatch, url.render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        get_settings.cache_clear()


def test_postgres_auth_api_roundtrip_and_persisted_reuse_revocation(migrated_database, monkeypatch):
    engine = migrated_database
    application = build_client(engine, monkeypatch)
    with TestClient(application) as client:
        assert register(client).status_code == 201
        assert register(client).status_code == 409
        first = login(client).json()
        raw = client.cookies.get("boso-dev-refresh")
        csrf = first["csrf_token"]
        assert me(client, first["access_token"]).status_code == 200
        assert post(client, "refresh", csrf=csrf).status_code == 200
        client.cookies.set("boso-dev-refresh", raw, domain="testserver.local", path="/")
        assert post(client, "refresh", csrf=csrf).status_code == 401
        assert me(client, first["access_token"]).status_code == 401
        second = login(client).json()
        assert post(client, "logout", csrf=second["csrf_token"]).status_code == 204
        assert me(client, second["access_token"]).status_code == 401
    with Session(engine) as db:
        assert set(db.scalars(select(AuthSession.revocation_reason))) == {"logout", "refresh_reuse"}


def test_postgres_concurrent_refresh_serializes_and_revokes_reused_family(
    migrated_database, monkeypatch
):
    engine = migrated_database
    settings = get_settings()
    with Session(engine) as db:
        user = service.signup(db, "race@example.com", "test-only-concurrent-password")
        grant = service.login(db, user.email, "test-only-concurrent-password")
        csrf = security.new_csrf(settings, grant.session_id)
        db.commit()

    barrier = Barrier(2)
    original = repository.session_by_id

    def synchronized_lock(db, session_id, *, lock=False):
        if lock:
            barrier.wait(timeout=10)
        return original(db, session_id, lock=lock)

    monkeypatch.setattr(repository, "session_by_id", synchronized_lock)

    def refresh_once():
        with Session(engine) as db:
            result = service.refresh(db, settings, grant.refresh_token, csrf, csrf)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: refresh_once(), range(2)))
    assert sum(result is not None for result in (first, second)) == 1
    winner = first or second
    with Session(engine) as db:
        session = db.get(AuthSession, grant.session_id)
        assert session.revocation_reason == "refresh_reuse"
        assert session.revoked_at is not None
        assert db.scalar(select(func.count()).select_from(RefreshToken)) == 2
        access, _ = security.issue_access(
            settings, winner.user_id, winner.session_id, winner.expires_at
        )
        with pytest.raises(AppError) as error:
            service.authenticated_user(db, settings, access)
        assert error.value.status == 401


def test_postgres_simultaneous_signup_preserves_case_insensitive_uniqueness(migrated_database):
    engine = migrated_database
    barrier = Barrier(2)

    def signup_once():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                service.signup(db, "duplicate@example.com", "test-only-concurrent-password")
                db.commit()
                return 201
            except AppError as error:
                db.rollback()
                if getattr(error, "status", None) == 409:
                    return 409
                raise

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: signup_once(), range(2))) == [201, 409]
