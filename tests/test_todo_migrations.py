from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from test_auth_migrations import migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database
from test_policy_data import policy_item as policy_item
from test_todos import TODAY, seed_policy, seed_user

from alembic import command
from app.models import UserTodo
from app.modules.todos import repository, service


def test_postgres_todo_migration_rls_and_concurrent_sync(
    postgres_database, monkeypatch, policy_item
):
    url, engine, role = postgres_database
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    config = migration_config(monkeypatch, url)
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db, db.begin():
        user_id = seed_user(db)
        seed_policy(db, policy_item)
    barrier = Barrier(2)
    original = repository.lock_owner

    def locked(*args):
        barrier.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(repository, "lock_owner", locked)

    def once(_):
        with Session(engine) as db, db.begin():
            return service.synchronize(db, user_id).created

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(once, range(2))) == [0, 1]
    with Session(engine) as db:
        assert len(db.scalars(select(UserTodo)).all()) == 1
    with engine.begin() as connection:
        assert connection.scalar(
            text("SELECT relrowsecurity FROM pg_class WHERE oid='public.user_todos'::regclass")
        )
        for client_role in ("anon", "authenticated", "service_role"):
            assert not connection.scalar(
                text("SELECT has_table_privilege(:role,'public.user_todos','SELECT')"),
                {"role": client_role},
            )
        connection.exec_driver_sql(f'GRANT SELECT, INSERT ON public.user_todos TO "{role}"')
    with engine.connect() as connection:
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        assert connection.scalar(text("SELECT count(*) FROM public.user_todos")) == 0
        with pytest.raises(ProgrammingError):
            connection.exec_driver_sql(
                "INSERT INTO public.user_todos(id) VALUES(gen_random_uuid())"
            )
    command.downgrade(config, "20261127_0003")
    assert "user_todos" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
