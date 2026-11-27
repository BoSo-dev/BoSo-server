import os
import re
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.core.database_url import resolve_database_url
from app.core.db import make_engine
from app.models import AuthSession, RefreshToken, User

REVISION = "20261030_0001"
AUTH_TABLES = {"users", "auth_sessions", "refresh_tokens"}
CLIENT_ROLES = ("anon", "authenticated", "service_role")


@pytest.fixture(autouse=True)
def settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def migration_config(monkeypatch, database_url, output_buffer=None):
    """Both URLs are explicit; abort before opening any unexpected database."""
    expected = resolve_database_url(database_url, migration=True)
    value = expected.render_as_string(hide_password=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", value)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", value)
    get_settings.cache_clear()

    def isolated_engine(url, **kwargs):
        if resolve_database_url(url) != expected:
            pytest.fail("Migration attempted to leave its isolated test database", pytrace=False)
        return make_engine(url, **kwargs)

    monkeypatch.setattr("app.core.db.make_engine", isolated_engine)
    return Config("alembic.ini", output_buffer=output_buffer)


def test_sqlite_migration_upgrade_downgrade_upgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'auth-migration.db'}"
    config = migration_config(monkeypatch, url)
    engine = make_engine(url)
    try:
        command.upgrade(config, REVISION)
        assert AUTH_TABLES <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_heads() == (REVISION,)
        command.downgrade(config, "base")
        assert not AUTH_TABLES.intersection(inspect(engine).get_table_names())
        command.upgrade(config, REVISION)
        assert AUTH_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_offline_migration_sql_targets_only_auth_tables(dialect, monkeypatch):
    url = (
        "sqlite:///unused-test.db"
        if dialect == "sqlite"
        else "postgresql+psycopg://test_user:test_password@localhost/boso_test"
    )
    output = StringIO()
    config = migration_config(monkeypatch, url, output)
    command.upgrade(config, REVISION, sql=True)
    sql = output.getvalue()
    assert "auth.users" not in sql
    assert "CREATE ROLE" not in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql
    assert "uq_refresh_tokens_unconsumed_session" in sql
    assert "WHERE used_at IS NULL" in sql
    assert "ON DELETE CASCADE" in sql
    if dialect == "postgresql":
        for table in AUTH_TABLES:
            assert f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY' in sql
            assert f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC' in sql
        for role in CLIENT_ROLES:
            assert f"'{role}'" in sql
        assert "VARCHAR(64)" in sql
    else:
        assert "ROW LEVEL SECURITY" not in sql
        assert "REVOKE" not in sql


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_offline_downgrade_drops_only_auth_tables_in_dependency_order(dialect, monkeypatch):
    url = (
        "sqlite:///unused-test.db"
        if dialect == "sqlite"
        else "postgresql+psycopg://test_user:test_password@localhost/boso_test"
    )
    output = StringIO()
    config = migration_config(monkeypatch, url, output)
    command.downgrade(config, f"{REVISION}:base", sql=True)
    sql = output.getvalue()
    prefix = "public." if dialect == "postgresql" else ""
    assert (
        sql.index(f"DROP TABLE {prefix}refresh_tokens")
        < sql.index(f"DROP TABLE {prefix}auth_sessions")
        < sql.index(f"DROP TABLE {prefix}users")
    )
    assert "auth.users" not in sql
    assert "DROP SCHEMA" not in sql
    assert "DROP ROLE" not in sql


def isolated_postgres_url(value):
    url = resolve_database_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").endswith("_test")
        or set(url.query) - {"sslmode"}
        or os.getenv("PGHOSTADDR")
        or os.getenv("PGSERVICE")
    ):
        pytest.fail(
            "Use a local disposable PostgreSQL *_test database without target overrides",
            pytrace=False,
        )
    return url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://test_user:test_password@test.pooler.supabase.com/boso_test",
        "postgresql://test_user:test_password@localhost/postgres",
        "postgresql://test_user:test_password@localhost/boso_test?dbname=production",
        "postgresql://test_user:test_password@localhost/boso_test?service=production",
        "sqlite:///boso_test",
    ],
)
def test_postgres_migration_guard_rejects_non_disposable_targets(url):
    with pytest.raises(pytest.fail.Exception, match="local disposable PostgreSQL"):
        isolated_postgres_url(url)


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE"])
def test_postgres_migration_guard_rejects_environment_target_overrides(name, monkeypatch):
    monkeypatch.setenv(name, "test-override")
    with pytest.raises(pytest.fail.Exception, match="local disposable PostgreSQL"):
        isolated_postgres_url("postgresql://test_user:test_password@localhost/boso_test")


@pytest.fixture(scope="module")
def postgres_admin():
    """Opt-in, local disposable PostgreSQL cluster only; never read .env."""
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL not set; PostgreSQL auth migration/RLS unverified")
    url = isolated_postgres_url(value)
    engine = make_engine(url, null_pool=True).execution_options(isolation_level="AUTOCOMMIT")
    created_roles = []
    probe_role = f"boso_auth_probe_{uuid4().hex}"
    try:
        with engine.connect() as connection:
            if not connection.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ):
                pytest.fail(
                    "Auth migration integration tests require a disposable superuser cluster",
                    pytrace=False,
                )
            for role in (*CLIENT_ROLES, probe_role):
                exists = connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
                )
                if not exists:
                    connection.exec_driver_sql(
                        f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'
                    )
                    created_roles.append(role)
        yield engine, url, probe_role
    finally:
        try:
            with engine.connect() as connection:
                for role in reversed(created_roles):
                    connection.exec_driver_sql(f'DROP ROLE "{role}"')
        finally:
            engine.dispose()


@pytest.fixture
def postgres_database(postgres_admin):
    admin, source_url, probe_role = postgres_admin
    name = f"boso_auth_test_{uuid4().hex}"
    # Only this generated database is created/dropped, not TEST_DATABASE_URL itself.
    if not re.fullmatch(r"boso_auth_test_[0-9a-f]{32}", name):
        pytest.fail("Unsafe disposable database name", pytrace=False)
    created = False
    engine = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        url = source_url.set(database=name)
        engine = make_engine(url, null_pool=True)
        with engine.begin() as connection:
            roles = ", ".join(f'"{role}"' for role in CLIENT_ROLES)
            # Simulate Supabase grants inherited by newly created public tables.
            connection.exec_driver_sql(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO {roles}"
            )
            connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO {roles}, "{probe_role}"')
        yield url, engine, probe_role
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')


def seed_graph(engine):
    created = datetime(2026, 10, 30, tzinfo=UTC)
    with Session(engine) as db:
        user = User(email="member@example.invalid", password_hash="test-only-hash")
        session = AuthSession(user=user, created_at=created, expires_at=created + timedelta(days=7))
        RefreshToken(
            session=session, token_hash="a" * 64, created_at=created, expires_at=session.expires_at
        )
        db.add(user)
        db.commit()
        return user.id, session.id


def test_postgres_upgrade_check_downgrade_preserves_supabase_auth_schema(
    postgres_database, monkeypatch
):
    url, engine, _ = postgres_database
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA auth")
        connection.exec_driver_sql("CREATE TABLE auth.users (marker integer PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO auth.users VALUES (1)")
    config = migration_config(monkeypatch, url)
    command.upgrade(config, "head")
    command.check(config)
    assert AUTH_TABLES <= set(inspect(engine).get_table_names(schema="public"))
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_heads() == (
            ScriptDirectory.from_config(config).get_current_head(),
        )
    command.downgrade(config, "base")
    assert not AUTH_TABLES.intersection(inspect(engine).get_table_names(schema="public"))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT marker FROM auth.users")) == 1
    command.upgrade(config, "head")
    command.check(config)


def test_postgres_types_constraints_indexes_and_cascade(postgres_database, monkeypatch):
    url, engine, _ = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    user_id, _ = seed_graph(engine)
    inspector = inspect(engine)
    for table in AUTH_TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert str(columns["id"]["type"]) == "UUID"
        assert columns["created_at"]["type"].timezone is True
    token_columns = {column["name"]: column for column in inspector.get_columns("refresh_tokens")}
    assert token_columns["token_hash"]["type"].length == 64
    assert "ck_refresh_tokens_hash_length" in {
        c["name"] for c in inspector.get_check_constraints("refresh_tokens")
    }
    index = next(
        i
        for i in inspector.get_indexes("refresh_tokens")
        if i["name"] == "uq_refresh_tokens_unconsumed_session"
    )
    assert index["unique"]
    assert "used_at IS NULL" in str(index["dialect_options"]["postgresql_where"])
    with engine.begin() as connection:
        connection.execute(User.__table__.delete().where(User.id == user_id))
        assert connection.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert connection.scalar(select(func.count()).select_from(RefreshToken)) == 0


@pytest.mark.parametrize(
    "violation",
    ["email", "hash_length", "token_hash", "unconsumed", "expiry", "revocation", "foreign_key"],
)
def test_postgres_constraints_reject_invalid_rows(violation, postgres_database, monkeypatch):
    url, engine, _ = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    user_id, session_id = seed_graph(engine)
    created = datetime(2026, 10, 30, tzinfo=UTC)
    expires = created + timedelta(days=7)
    with Session(engine) as db:
        if violation == "email":
            row = User(email="MEMBER@example.invalid", password_hash="test-only-hash")
        elif violation in {"hash_length", "token_hash", "unconsumed", "foreign_key"}:
            row = RefreshToken(
                session_id=uuid4() if violation == "foreign_key" else session_id,
                token_hash="a" * 63
                if violation == "hash_length"
                else ("a" * 64 if violation == "token_hash" else "b" * 64),
                created_at=created,
                expires_at=expires,
                used_at=None if violation == "unconsumed" else created,
            )
        else:
            row = AuthSession(
                user_id=user_id,
                created_at=created,
                expires_at=created if violation == "expiry" else expires,
                revoked_at=created if violation == "revocation" else None,
            )
        db.add(row)
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("role", CLIENT_ROLES)
def test_postgres_client_role_direct_grants_are_removed(role, postgres_database, monkeypatch):
    url, engine, _ = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    with engine.connect() as connection:
        for table in AUTH_TABLES:
            for privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
            ):
                assert not connection.scalar(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": role, "table": f"public.{table}", "privilege": privilege},
                )
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        with pytest.raises(ProgrammingError) as error:
            connection.exec_driver_sql("SELECT * FROM public.users")
        assert error.value.orig.sqlstate == "42501"


def test_postgres_rls_denies_rows_even_with_table_privileges(postgres_database, monkeypatch):
    url, engine, probe_role = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    seed_graph(engine)
    with engine.begin() as connection:
        for table in AUTH_TABLES:
            assert (
                connection.scalar(
                    text(
                        "SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:table AS regclass)"
                    ),
                    {"table": f"public.{table}"},
                )
                is True
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :table"
                    ),
                    {"table": table},
                )
                == 0
            )
            connection.exec_driver_sql(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" TO "{probe_role}"'
            )
    with engine.connect() as connection:
        connection.exec_driver_sql(f'SET LOCAL ROLE "{probe_role}"')
        for table in AUTH_TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM public."{table}"')) == 0
        assert connection.exec_driver_sql("UPDATE public.users SET is_active = false").rowcount == 0
        assert connection.exec_driver_sql("DELETE FROM public.users").rowcount == 0
        with pytest.raises(ProgrammingError) as error:
            connection.execute(
                text(
                    "INSERT INTO public.users (id, email, password_hash) VALUES (:id, 'blocked@example.invalid', 'test-only-hash')"
                ),
                {"id": uuid4()},
            )
        assert error.value.orig.sqlstate == "42501"
