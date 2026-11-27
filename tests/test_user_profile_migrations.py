from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import StringIO
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from test_auth_migrations import CLIENT_ROLES, migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database

from alembic import command
from app.core.config import get_settings
from app.core.db import make_engine
from app.models import User, UserProfile, UserTransportCard, UserTransportMode
from app.modules.users import repository, service
from app.modules.users.schemas import ProfilePatch

REVISION = "20261127_0002"
PREVIOUS = "20261030_0001"
TABLES = {"user_profiles", "user_transport_cards", "user_transport_modes"}


@pytest.fixture(autouse=True)
def settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def seed_profile(engine):
    with Session(engine) as db:
        user = User(email="profile@example.invalid", password_hash="test-only-hash")
        db.add(user)
        db.flush()
        db.add(UserProfile(user_id=user.id, birth_date=date(2000, 1, 1), region_code="seoul"))
        db.flush()
        db.add(UserTransportCard(user_id=user.id, card_code="k_pass"))
        db.add(UserTransportMode(user_id=user.id, mode_code="bus"))
        db.commit()
        return user.id


def test_sqlite_profile_upgrade_downgrade_preserves_auth_user(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'profile-migration.db'}"
    config = migration_config(monkeypatch, url)
    engine = make_engine(url)
    try:
        command.upgrade(config, REVISION)
        user_id = seed_profile(engine)
        assert TABLES <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_heads() == (REVISION,)
        command.downgrade(config, PREVIOUS)
        assert not TABLES.intersection(inspect(engine).get_table_names())
        with Session(engine) as db:
            assert db.get(User, user_id).email == "profile@example.invalid"
        command.upgrade(config, REVISION)
        assert TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_offline_profile_revision_changes_only_profile_tables(dialect, direction, monkeypatch):
    url = (
        "sqlite:///unused.db"
        if dialect == "sqlite"
        else "postgresql+psycopg://test:test@localhost/boso_test"
    )
    output = StringIO()
    config = migration_config(monkeypatch, url, output)
    if direction == "upgrade":
        command.upgrade(config, f"{PREVIOUS}:{REVISION}", sql=True)
    else:
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    sql = output.getvalue()
    assert "auth.users" not in sql and "CREATE ROLE" not in sql
    assert "DROP SCHEMA" not in sql and "ALTER DEFAULT PRIVILEGES" not in sql
    assert "CREATE TABLE public.users" not in sql and "DROP TABLE public.users" not in sql
    if direction == "upgrade" and dialect == "postgresql":
        for table in TABLES:
            assert f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY' in sql
            assert f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC' in sql
    if direction == "downgrade":
        assert (
            sql.index("user_transport_modes")
            < sql.index("user_transport_cards")
            < sql.index("user_profiles")
        )


@pytest.fixture
def profile_postgres(postgres_database, monkeypatch):
    url, engine, probe_role = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    return engine, probe_role


def test_postgres_profile_migration_check_and_downgrade_preserve_auth(
    postgres_database, monkeypatch
):
    url, engine, _ = postgres_database
    config = migration_config(monkeypatch, url)
    command.upgrade(config, "head")
    command.check(config)
    user_id = seed_profile(engine)
    command.downgrade(config, PREVIOUS)
    assert not TABLES.intersection(inspect(engine).get_table_names(schema="public"))
    with Session(engine) as db:
        assert db.get(User, user_id) is not None
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("role", CLIENT_ROLES)
def test_postgres_profile_client_roles_have_no_direct_grants(profile_postgres, role):
    engine, _ = profile_postgres
    with engine.connect() as connection:
        for table in TABLES:
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
            connection.exec_driver_sql("SELECT * FROM public.user_profiles")
        assert error.value.orig.sqlstate == "42501"


def test_postgres_profile_rls_blocks_rows_even_with_grants(profile_postgres):
    engine, probe_role = profile_postgres
    user_id = seed_profile(engine)
    with engine.begin() as connection:
        for table in TABLES:
            assert connection.scalar(
                text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),
                {"table": f"public.{table}"},
            )
            connection.exec_driver_sql(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON public."{table}" TO "{probe_role}"'
            )
    with engine.connect() as connection:
        connection.exec_driver_sql(f'SET LOCAL ROLE "{probe_role}"')
        for table in TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM public."{table}"')) == 0
        assert (
            connection.exec_driver_sql(
                "UPDATE public.user_profiles SET region_code='busan'"
            ).rowcount
            == 0
        )
        assert connection.exec_driver_sql("DELETE FROM public.user_profiles").rowcount == 0
        with pytest.raises(ProgrammingError) as error:
            connection.execute(
                text(
                    "INSERT INTO public.user_profiles (user_id, region_code) VALUES (:id, 'seoul')"
                ),
                {"id": user_id},
            )
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "violation", ["region", "birth_date", "card", "mode", "duplicate", "parent"]
)
def test_postgres_profile_constraints(profile_postgres, violation):
    engine, _ = profile_postgres
    user_id = seed_profile(engine)
    with Session(engine) as db:
        if violation in {"region", "birth_date"}:
            row = db.get(UserProfile, user_id)
            if violation == "region":
                row.region_code = "invalid"
            else:
                row.birth_date = date(1899, 1, 1)
        elif violation == "mode":
            db.add(UserTransportMode(user_id=user_id, mode_code="invalid"))
        else:
            db.add(
                UserTransportCard(
                    user_id=uuid4() if violation == "parent" else user_id,
                    card_code="invalid" if violation == "card" else "k_pass",
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()


def test_postgres_profile_user_delete_cascades(profile_postgres):
    engine, _ = profile_postgres
    user_id = seed_profile(engine)
    with engine.begin() as connection:
        connection.execute(User.__table__.delete().where(User.id == user_id))
        for model in (UserProfile, UserTransportCard, UserTransportMode):
            assert connection.scalar(select(func.count()).select_from(model)) == 0


def test_postgres_concurrent_initial_profile_updates_are_serialized(profile_postgres, monkeypatch):
    engine, _ = profile_postgres
    with Session(engine) as db:
        user = User(email="race@example.invalid", password_hash="test-only-hash")
        db.add(user)
        db.commit()
        user_id = user.id
    barrier = Barrier(2)
    original = repository.lock_user

    def synchronized(db, owner):
        barrier.wait(timeout=10)
        return original(db, owner)

    monkeypatch.setattr(repository, "lock_user", synchronized)

    def update_once(body):
        with Session(engine) as db:
            user = db.get(User, user_id)
            service.update_profile(db, user, ProfilePatch.model_validate(body))
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update_once, [{"region_code": "seoul"}, {"birth_date": "2000-01-01"}]))
    with Session(engine) as db:
        profile = db.get(UserProfile, user_id)
        assert profile.region_code == "seoul" and profile.birth_date == date(2000, 1, 1)
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 1


def test_postgres_profile_read_is_consistent_during_a_committed_update(profile_postgres):
    engine, _ = profile_postgres
    user_id = seed_profile(engine)
    changed = False

    def update_after_select(connection, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if (
            changed
            or not statement.lstrip().upper().startswith("SELECT")
            or "user_profiles" not in statement
        ):
            return
        changed = True
        # Commit a second connection's update after the read statement executes,
        # before its result is assembled. Every returned field must stay in the
        # original statement snapshot, not mix old region and new child lists.
        with engine.begin() as writer:
            writer.execute(
                UserProfile.__table__.update()
                .where(UserProfile.user_id == user_id)
                .values(region_code="busan")
            )
            writer.execute(
                UserTransportCard.__table__.delete().where(UserTransportCard.user_id == user_id)
            )
            writer.execute(
                UserTransportCard.__table__.insert().values(
                    user_id=user_id, card_code="climate_card"
                )
            )
            writer.execute(
                UserTransportMode.__table__.delete().where(UserTransportMode.user_id == user_id)
            )
            writer.execute(
                UserTransportMode.__table__.insert().values(user_id=user_id, mode_code="subway")
            )

    event.listen(engine, "after_cursor_execute", update_after_select)
    try:
        with Session(engine) as reader:
            _, first = service.profile_state(reader, user_id, date(2026, 11, 27))
            assert changed
            assert (first.region_code, first.transport_cards, first.transport_modes) == (
                "seoul",
                ["k_pass"],
                ["bus"],
            )
            _, second = service.profile_state(reader, user_id, date(2026, 11, 27))
            assert (second.region_code, second.transport_cards, second.transport_modes) == (
                "busan",
                ["climate_card"],
                ["subway"],
            )
    finally:
        event.remove(engine, "after_cursor_execute", update_after_select)
