from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth_migrations import migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database
from test_policy_data import policy_item as policy_item
from test_todos import TODAY, seed_todo_graph, seed_user

from alembic import command
from app.models import Notification
from app.modules.notifications import service
from app.modules.todos import repository as todo_repository


def test_postgres_notification_constraints_rls_and_concurrent_dedup(
    postgres_database, monkeypatch, policy_item
):
    url, engine, role = postgres_database
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    config = migration_config(monkeypatch, url)
    command.upgrade(config, "head")
    command.check(config)
    owner, _, _, _ = seed_todo_graph(engine, policy_item)
    barrier = Barrier(2)
    original = todo_repository.lock_owner

    def locked(*args):
        barrier.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(todo_repository, "lock_owner", locked)

    def once(_):
        with Session(engine) as db, db.begin():
            return service.synchronize(db, owner).created

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(once, range(2))) == [0, 2]
    with Session(engine) as db:
        rows = db.scalars(select(Notification)).all()
        assert len(rows) == 2
        other = seed_user(db, "foreign-notification@example.invalid")
        rows[0].user_id = other
        with pytest.raises(IntegrityError):
            db.commit()
    with engine.begin() as connection:
        assert connection.scalar(
            text("SELECT relrowsecurity FROM pg_class WHERE oid='public.notifications'::regclass")
        )
        for client_role in ("anon", "authenticated", "service_role"):
            assert not connection.scalar(
                text("SELECT has_table_privilege(:role,'public.notifications','SELECT')"),
                {"role": client_role},
            )
        connection.exec_driver_sql(f'GRANT SELECT ON public.notifications TO "{role}"')
    with engine.connect() as connection:
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        assert connection.scalar(text("SELECT count(*) FROM public.notifications")) == 0
    command.downgrade(config, "20261127_0110")
    assert "notifications" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
