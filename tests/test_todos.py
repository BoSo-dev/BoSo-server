import copy
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth_api import auth_api as auth_api
from test_policy_data import batch_for
from test_policy_data import policy_item as policy_item
from test_user_profile import profile_api as profile_api

from app.core.db import Base, make_engine
from app.core.errors import AppError
from app.models import Policy, User, UserProfile, UserTodo
from app.modules.policies.schemas import EligibilityRules
from app.modules.policies.service import import_policies
from app.modules.todos import service
from app.modules.todos.eligibility import evaluate_eligibility
from app.modules.users.schemas import PersonalizationContext

TODAY = date(2026, 11, 27)


@pytest.fixture(autouse=True)
def todo_date(monkeypatch):
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)


@pytest.fixture
def todo_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'todos.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def seed_user(db, email="todo@example.invalid"):
    user = User(email=email, password_hash="test-only-hash")
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id, birth_date=date(2000, 1, 1), region_code="seoul"))
    db.flush()
    return user.id


def seed_policy(db, policy_item):
    data = copy.deepcopy(policy_item)
    data["eligibility"].update(
        additional_requirements=[],
        requires_confirmation=False,
        transport_cards=[],
        transport_modes=[],
    )
    data["actions"][0]["due_date"] = TODAY.isoformat()
    import_policies(db, batch_for(data))
    db.flush()
    return data, db.scalar(select(Policy.id).where(Policy.policy_key == data["policy_key"]))


def seed_todo_graph(engine, policy_item):
    with Session(engine) as db, db.begin():
        owner = seed_user(db)
        data, policy_id = seed_policy(db, policy_item)
        service.synchronize(db, owner, reference_date=TODAY)
        todo_id = db.scalar(select(UserTodo.id))
    return owner, policy_id, todo_id, data


@pytest.mark.parametrize(
    "profile_values,rules_values,state",
    [
        ({"age": None}, {"age_min": 19}, "unknown"),
        ({"age": 18}, {"age_min": 19}, "not_eligible"),
        ({"age": 19}, {"age_min": 19, "age_max": 19}, "eligible"),
        ({"age": 20}, {"age_max": 19}, "not_eligible"),
        ({"region_code": None}, {"region_codes": ["seoul"]}, "unknown"),
        ({"region_code": "busan"}, {"region_codes": ["seoul"]}, "not_eligible"),
        ({"transport_cards": ["other_or_none"]}, {"transport_cards": ["k_pass"]}, "unknown"),
        ({"transport_modes": []}, {"transport_modes": ["bus"]}, "unknown"),
        ({}, {"requires_confirmation": True}, "unknown"),
        ({}, {"additional_requirements": ["income"], "requires_confirmation": True}, "unknown"),
        ({}, {}, "eligible"),
    ],
)
def test_eligibility_is_conservative(profile_values, rules_values, state):
    data = dict(
        user_id=uuid4(),
        reference_date=TODAY,
        age=25,
        region_code="seoul",
        transport_cards=["k_pass"],
        transport_modes=["bus"],
        is_complete=True,
        missing_fields=[],
    )
    data.update(profile_values)
    rules = EligibilityRules.model_validate({"requires_confirmation": False, **rules_values})
    assert evaluate_eligibility(rules, PersonalizationContext(**data)).state == state


def test_sync_repeat_completion_and_expiry_boundary(todo_engine, policy_item):
    owner, _, todo_id, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        assert service.synchronize(db, owner).created == 0
        assert service.read_todo(db, owner, todo_id).is_overdue is False
        result = service.change_completion(db, owner, todo_id, True)
        assert result.status == "completed"
        completed_at = result.completed_at
        assert service.change_completion(db, owner, todo_id, True).completed_at == completed_at
        assert service.synchronize(db, owner).created == 0
        assert service.summary(db, owner).completed == 1
        assert service.change_completion(db, owner, todo_id, False).status == "pending"


def test_versions_preserve_completed_and_archive_removed_actions(todo_engine, policy_item):
    owner, policy_id, todo_id, data = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        service.change_completion(db, owner, todo_id, True)
        next_data = copy.deepcopy(data)
        next_data.update(version=2, effective_from="2026-11-01")
        next_data["actions"].append({**next_data["actions"][0], "action_key": "new-action"})
        import_policies(db, batch_for(next_data))
        assert service.synchronize(db, owner).created == 1
        assert service.read_todo(db, owner, todo_id).status == "completed"
        original_version = service.read_todo(db, owner, todo_id).policy_version_id
        reopened = service.change_completion(db, owner, todo_id, False)
        assert reopened.policy_version_id != original_version
        service.change_completion(db, owner, todo_id, True)
        third = copy.deepcopy(next_data)
        third.update(version=3, effective_from="2026-11-27", lifecycle="ended", actions=[])
        import_policies(db, batch_for(third))
        assert service.synchronize(db, owner).archived == 1
        assert service.read_todo(db, owner, todo_id).status == "completed"
        with pytest.raises(AppError) as error:
            service.change_completion(db, owner, todo_id, False)
        assert error.value.code == "TODO_NOT_ACTIVE"
        assert len(service.related_todos(db, owner, [policy_id])) == 1


def test_profile_changes_archive_and_restore_without_duplicates(todo_engine, policy_item):
    owner, _, todo_id, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        db.get(UserProfile, owner).region_code = "busan"
        db.flush()
        assert service.synchronize(db, owner).archived == 1
        assert service.read_todo(db, owner, todo_id).archived_reason == "not_eligible"
        db.get(UserProfile, owner).region_code = "seoul"
        db.flush()
        assert service.synchronize(db, owner).updated == 1
        assert service.list_todos(db, owner).total == 1


def test_overdue_and_other_owner_access(todo_engine, policy_item, monkeypatch):
    owner, policy_id, todo_id, _ = seed_todo_graph(todo_engine, policy_item)
    monkeypatch.setattr(service, "today_kst", lambda: TODAY + timedelta(days=1))
    with Session(todo_engine) as db, db.begin():
        other = seed_user(db, "other@example.invalid")
        assert service.read_todo(db, owner, todo_id).is_overdue
        assert service.summary(db, owner).overdue == 1
        assert service.list_todos(db, other, "all").total == 0
        assert service.related_todos(db, other, [policy_id]) == []
        for operation in (
            lambda: service.read_todo(db, other, todo_id),
            lambda: service.change_completion(db, other, todo_id, True),
        ):
            with pytest.raises(AppError) as error:
                operation()
            assert error.value.code == "TODO_NOT_FOUND"


def test_todo_api_auth_owner_validation_and_commit(profile_api, policy_item):
    client, engine, _, headers = profile_api
    with Session(engine) as db, db.begin():
        seed_policy(db, policy_item)
    assert client.post("/api/v1/todos/sync", json={}, headers=headers).json()["created"] == 0
    assert (
        client.patch(
            "/api/v1/me", json={"region_code": "seoul", "birth_date": "2000-01-01"}, headers=headers
        ).status_code
        == 200
    )
    response = client.post("/api/v1/todos/sync", json={}, headers=headers)
    assert response.status_code == 200 and response.json()["created"] == 1
    page = client.get("/api/v1/todos", headers=headers)
    assert page.headers["Cache-Control"] == "no-store"
    todo_id = page.json()["items"][0]["id"]
    assert (
        client.patch(
            "/api/v1/todos/" + todo_id, json={"completed": True}, headers=headers
        ).status_code
        == 200
    )
    assert client.get("/api/v1/todos/summary", headers=headers).json()["completed"] == 1
    assert client.get("/api/v1/todos").status_code == 401
    assert (
        client.post(
            "/api/v1/todos/sync", json={"user_id": str(uuid4())}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/todos/" + todo_id, json={"completed": "true"}, headers=headers
        ).status_code
        == 422
    )
    assert client.get("/api/v1/todos?limit=101", headers=headers).status_code == 422
