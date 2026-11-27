import copy

from sqlalchemy.orm import Session
from test_auth_migrations import migration_config
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database
from test_policy_api import TODAY, publish
from test_policy_data import policy_item as policy_item
from test_todos import seed_user

from alembic import command
from app.modules.policies import catalog_service as service


def test_postgres_catalog_window_search_history_and_personalization(
    postgres_database, monkeypatch, policy_item
):
    url, engine, _ = postgres_database
    command.upgrade(migration_config(monkeypatch, url), "head")
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    policy_item["eligibility"].update(requires_confirmation=False, additional_requirements=[])
    policy_item.update(title="Original", summary="100%_value")
    policy_id = publish(engine, policy_item)
    with Session(engine) as db, db.begin():
        owner = seed_user(db)
        assert service.list_policies(db, q="%_").total == 1
        assert service.for_user(db, owner, eligibility="eligible").total == 1
        assert service.read_policy(db, policy_id).policy_id == policy_id
    ended = copy.deepcopy(policy_item)
    ended.update(
        version=2, title="Ended", lifecycle="ended", effective_from="2026-11-01", actions=[]
    )
    publish(engine, ended)
    with Session(engine) as db:
        assert service.list_policies(db).total == 0
        assert service.list_policies(db, q="Original", state="all").total == 0
        assert service.list_policies(db, state="ended", offset=100).total == 1
        assert service.for_user(db, owner, state="all", eligibility="not_eligible").total == 1
        assert service.history_page(db, policy_id).total == 2
        assert "lifecycle" in service.changes(db, policy_id).changed_fields
