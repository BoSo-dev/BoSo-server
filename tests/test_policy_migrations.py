from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from test_auth_migrations import CLIENT_ROLES, migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database
from test_policy_data import batch_for
from test_policy_data import policy_item as policy_item

from alembic import command
from app.core.db import make_engine
from app.models import Policy, PolicyAction, PolicyVersion
from app.modules.policies import repository
from app.modules.policies.service import PolicyImportError, import_policies

REVISION = "20261127_0003"
PREVIOUS = "20261127_0002"
TABLES = {"policies", "policy_versions", "policy_sources", "policy_actions"}


@pytest.fixture
def policy_postgres(postgres_database, monkeypatch):
    url, engine, role = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    return engine, role


def test_sqlite_policy_upgrade_downgrade_preserves_prior_tables(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'policies-migration.db'}"
    config = migration_config(monkeypatch, url)
    engine = make_engine(url)
    try:
        command.upgrade(config, PREVIOUS)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, "head")
        assert TABLES <= set(inspect(engine).get_table_names())
        command.check(config)
        command.downgrade(config, PREVIOUS)
        assert set(inspect(engine).get_table_names()) == before
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_offline_policy_sql_changes_only_its_tables(monkeypatch, dialect, direction):
    url = (
        "sqlite:///unused.db"
        if dialect == "sqlite"
        else "postgresql://test:test@localhost/boso_test"
    )
    output = StringIO()
    config = migration_config(monkeypatch, url, output)
    if direction == "upgrade":
        command.upgrade(config, f"{PREVIOUS}:{REVISION}", sql=True)
    else:
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    sql = output.getvalue()
    assert "auth.users" not in sql and "CREATE ROLE" not in sql and "DROP SCHEMA" not in sql
    assert "CREATE TABLE public.users" not in sql and "DROP TABLE public.users" not in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql
    if direction == "upgrade":
        assert "ON DELETE RESTRICT" in sql
        if dialect == "postgresql":
            for table in TABLES:
                assert f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY' in sql
                assert f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC' in sql
    else:
        assert sql.index(
            "DROP TABLE " + ("public." if dialect == "postgresql" else "") + "policy_actions"
        ) < sql.index("DROP TABLE " + ("public." if dialect == "postgresql" else "") + "policies")


def test_postgres_policy_upgrade_check_downgrade(postgres_database, monkeypatch, policy_item):
    url, engine, _ = postgres_database
    config = migration_config(monkeypatch, url)
    command.upgrade(config, PREVIOUS)
    before = set(inspect(engine).get_table_names(schema="public"))
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db, db.begin():
        import_policies(db, batch_for(policy_item))
    command.downgrade(config, PREVIOUS)
    assert set(inspect(engine).get_table_names(schema="public")) == before
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("role", CLIENT_ROLES)
def test_postgres_policy_direct_grants_removed(policy_postgres, role):
    engine, _ = policy_postgres
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
            connection.exec_driver_sql("SELECT * FROM public.policies")
        assert error.value.orig.sqlstate == "42501"


def test_postgres_policy_rls_default_deny(policy_postgres, policy_item):
    engine, role = policy_postgres
    with Session(engine) as db, db.begin():
        import_policies(db, batch_for(policy_item))
    with engine.begin() as connection:
        for table in TABLES:
            assert connection.scalar(
                text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),
                {"table": f"public.{table}"},
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename=:table"
                    ),
                    {"table": table},
                )
                == 0
            )
            connection.exec_driver_sql(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON public."{table}" TO "{role}"'
            )
    with engine.connect() as connection:
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        for table in TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM public."{table}"')) == 0
            assert connection.exec_driver_sql(f'DELETE FROM public."{table}"').rowcount == 0
        with pytest.raises(ProgrammingError) as error:
            connection.exec_driver_sql(
                "INSERT INTO public.policies (id,policy_key,is_example) VALUES (gen_random_uuid(),'blocked',false)"
            )
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "violation",
    ["version", "period", "hash", "category", "lifecycle", "duplicate_action", "parent_delete"],
)
def test_postgres_policy_constraints(policy_postgres, policy_item, violation):
    engine, _ = policy_postgres
    with Session(engine) as db, db.begin():
        import_policies(db, batch_for(policy_item))
    with Session(engine) as db:
        version = db.scalar(select(PolicyVersion))
        if violation == "version":
            version.version = 0
        elif violation == "period":
            version.effective_until = version.effective_from.replace(year=2025)
        elif violation == "hash":
            version.content_hash = "x" * 63
        elif violation == "category":
            version.category = "invalid"
        elif violation == "lifecycle":
            version.lifecycle = "invalid"
        elif violation == "duplicate_action":
            db.add(
                PolicyAction(
                    version_id=version.id,
                    action_key=policy_item["actions"][0]["action_key"],
                    title="Duplicate",
                    description="Duplicate",
                )
            )
        else:
            with pytest.raises(IntegrityError):
                db.execute(Policy.__table__.delete())
            return
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("conflicting", [False, True])
def test_postgres_simultaneous_first_import_is_serialized(
    policy_postgres, policy_item, monkeypatch, conflicting
):
    engine, _ = policy_postgres
    barrier = Barrier(2)
    original = repository.lock_policy

    def synchronized(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "lock_policy", synchronized)

    def once(index):
        item = {**policy_item, "summary": f"conflict-{index}"} if conflicting else policy_item
        try:
            with Session(engine) as db, db.begin():
                return import_policies(db, batch_for(item))
        except PolicyImportError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(once, (0, 1)))
    assert results.count({"created": 1, "unchanged": 0}) == 1
    assert (
        results.count("POLICY_VERSION_IMMUTABLE" if conflicting else {"created": 0, "unchanged": 1})
        == 1
    )
    with Session(engine) as db:
        assert len(db.scalars(select(Policy)).all()) == 1
        assert len(db.scalars(select(PolicyVersion)).all()) == 1
