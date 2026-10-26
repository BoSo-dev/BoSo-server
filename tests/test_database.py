import os

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.db import get_db, make_engine
from app.core.dependencies import DbSession
from app.main import create_app


def test_alembic_environment_on_fresh_database(tmp_path, monkeypatch):
    # Never migrate a database from the caller's .env in this unit test.
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "test")
    from app.core.config import get_settings

    def make_test_engine(url, **kwargs):
        # Stop before connecting if either setting ever escapes test isolation.
        if str(url) != database_url:
            pytest.fail("Alembic must use the isolated test database", pytrace=False)
        return make_engine(url, **kwargs)

    monkeypatch.setattr("app.core.db.make_engine", make_test_engine)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert str(settings.get_database_url()) == database_url
        assert str(settings.get_database_url(migration=True)) == database_url
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()


def test_database_session_rolls_back_on_failure(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    monkeypatch.setattr("app.core.db.get_engine", lambda: engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value INTEGER NOT NULL)"))

    dependency = get_db()
    db = next(dependency)
    db.execute(text("INSERT INTO probe (value) VALUES (1)"))
    with pytest.raises(RuntimeError, match="failed_request"):
        dependency.throw(RuntimeError("failed_request"))
    with Session(engine) as verification:
        assert verification.scalar(text("SELECT COUNT(*) FROM probe")) == 0
    engine.dispose()


def test_database_session_commits_on_success(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'commit.db'}")
    monkeypatch.setattr("app.core.db.get_engine", lambda: engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value INTEGER NOT NULL)"))

    dependency = get_db()
    db = next(dependency)
    db.execute(text("INSERT INTO probe (value) VALUES (1)"))
    with pytest.raises(StopIteration):
        next(dependency)
    with Session(engine) as verification:
        assert verification.scalar(text("SELECT COUNT(*) FROM probe")) == 1
    engine.dispose()


def test_commit_failure_returns_error_before_success_response(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'failed-commit.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value INTEGER NOT NULL)"))

    class FailingCommitSession(Session):
        def commit(self):
            raise OperationalError("commit", {}, Exception("secret-driver-message"))

    monkeypatch.setattr("app.core.db.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.core.db.sessionmaker",
        lambda *args, **kwargs: sessionmaker(*args, class_=FailingCommitSession, **kwargs),
    )
    application = create_app()

    @application.post("/transaction")
    def insert(db: DbSession):
        db.execute(text("INSERT INTO probe (value) VALUES (1)"))
        return {"created": True}

    with TestClient(application) as client:
        response = client.post("/transaction")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secret-driver-message" not in response.text
    with Session(engine) as verification:
        assert verification.scalar(text("SELECT COUNT(*) FROM probe")) == 0
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_postgres_connection():
    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+psycopg://"), "Use a test PostgreSQL URI"
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()
