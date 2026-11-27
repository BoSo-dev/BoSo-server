from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from test_auth_migrations import migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database
from test_todos import seed_user

from alembic import command
from app.modules.chat import repository, service
from app.modules.chat.schemas import ConversationCreate, TurnRequest


def test_postgres_chat_migration_private_rls_and_idempotent_race(postgres_database, monkeypatch):
    url, engine, role = postgres_database
    config = migration_config(monkeypatch, url)
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db, db.begin():
        user_id = seed_user(db)
        conversation = service.create_conversation(db, user_id, ConversationCreate())
    barrier = Barrier(2)
    original = repository.conversation

    def locked(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "conversation", locked)
    body = TurnRequest(request_id=uuid4(), question="안녕하세요")

    def once(_):
        with Session(engine) as db, db.begin():
            return service.send_message(db, user_id, conversation.id, body).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(once, range(2)))
    assert results[0] == results[1]
    with engine.begin() as connection:
        for table in ("chat_conversations", "chat_turns"):
            assert connection.scalar(
                text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),
                {"table": f"public.{table}"},
            )
            for client_role in ("anon", "authenticated", "service_role"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege(:role,:table,'SELECT')"),
                    {"role": client_role, "table": f"public.{table}"},
                )
            connection.exec_driver_sql(f'GRANT SELECT ON public."{table}" TO "{role}"')
    with engine.connect() as connection:
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        assert connection.scalar(text("SELECT count(*) FROM public.chat_conversations")) == 0
        assert connection.scalar(text("SELECT count(*) FROM public.chat_turns")) == 0
    command.downgrade(config, "20261127_0100")
    assert not {"chat_conversations", "chat_turns"}.intersection(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    command.check(config)
