import os

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from app.core.db import get_db, make_engine


def test_alembic_environment_on_fresh_database(tmp_path, monkeypatch):
    # Never migrate a database from the caller's .env in this unit test.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'migration.db'}")
    monkeypatch.setenv("APP_ENV", "test")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
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
