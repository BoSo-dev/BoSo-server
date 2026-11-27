from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth_api import auth_api as auth_api
from test_policy_data import policy_item as policy_item
from test_todos import TODAY, seed_todo_graph, seed_user
from test_todos import todo_engine as todo_engine
from test_user_profile import profile_api as profile_api

from app.core.errors import AppError
from app.models import Notification, UserProfile, UserTodo
from app.modules.notifications import service
from app.modules.todos import service as todos
from scripts import sync_notifications as job


@pytest.fixture(autouse=True)
def notification_date(monkeypatch):
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    monkeypatch.setattr(todos, "today_kst", lambda: TODAY)


def test_sync_dedup_read_and_read_all(todo_engine, policy_item):
    owner, _, _, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        assert service.synchronize(db, owner).created == 2
        assert service.synchronize(db, owner).created == 0
        assert service.unread_count(db, owner) == 2
        page = service.list_notifications(db, owner, True)
        assert page.total == 2
        first = service.mark_read(db, owner, page.items[0].id)
        assert first.read_at is not None
        assert service.mark_read(db, owner, first.id).read_at == first.read_at
        assert service.unread_count(db, owner) == 1
        assert service.mark_all_read(db, owner) == 1
        assert service.mark_all_read(db, owner) == 0
        assert service.list_notifications(db, owner, False).total == 2


@pytest.mark.parametrize("days,expected", [(-1, 1), (0, 2), (3, 2), (4, 1)])
def test_deadline_notification_boundaries(todo_engine, policy_item, days, expected):
    policy_item["actions"][0]["due_date"] = (TODAY + timedelta(days=days)).isoformat()
    # seed_todo_graph sets the baseline deadline; update its source before sync
    owner, _, todo_id, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        from app.models import PolicyAction

        todo = db.get(UserTodo, todo_id)
        db.get(PolicyAction, todo.action_id).due_date = TODAY + timedelta(days=days)
        db.flush()
        assert service.synchronize(db, owner).created == expected


def test_not_eligible_or_completed_todos_do_not_create_notifications(todo_engine, policy_item):
    owner, _, todo_id, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        todos.change_completion(db, owner, todo_id, True)
        assert service.synchronize(db, owner).created == 0
        db.get(UserTodo, todo_id).status = "pending"
        db.get(UserTodo, todo_id).completed_at = None
        db.get(UserProfile, owner).region_code = "busan"
        db.flush()
        assert service.synchronize(db, owner).created == 0
        assert db.get(UserTodo, todo_id).status == "archived"


def test_other_owner_cannot_read_or_count_notifications(todo_engine, policy_item):
    owner, _, _, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        other = seed_user(db, "notification-other@example.invalid")
        service.synchronize(db, owner)
        notification_id = db.scalar(select(Notification.id))
        assert service.unread_count(db, other) == 0
        assert service.list_notifications(db, other).items == []
        assert service.mark_all_read(db, other) == 0
        with pytest.raises(AppError) as error:
            service.mark_read(db, other, notification_id)
        assert error.value.code == "NOTIFICATION_NOT_FOUND"


def test_notification_api_privacy_and_validation(profile_api, policy_item):
    from test_todos import seed_policy

    client, engine, _, headers = profile_api
    with Session(engine) as db, db.begin():
        seed_policy(db, policy_item)
    client.patch(
        "/api/v1/me", json={"region_code": "seoul", "birth_date": "2000-01-01"}, headers=headers
    )
    assert (
        client.post("/api/v1/notifications/sync", json={}, headers=headers).json()["created"] == 2
    )
    response = client.get("/api/v1/notifications", headers=headers)
    assert response.headers["Cache-Control"] == "no-store"
    notification_id = response.json()["items"][0]["id"]
    assert client.get("/api/v1/notifications/unread-count", headers=headers).json()["count"] == 2
    assert (
        client.post(
            f"/api/v1/notifications/{notification_id}/read", json={}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post("/api/v1/notifications/read-all", json={}, headers=headers).json()["updated"]
        == 1
    )
    assert client.get("/api/v1/notifications").status_code == 401
    assert (
        client.post(
            "/api/v1/notifications/sync", json={"user_id": str(uuid4())}, headers=headers
        ).status_code
        == 422
    )


def test_job_default_does_not_connect(monkeypatch, capsys):
    monkeypatch.setattr(job, "get_settings", lambda: pytest.fail("No settings access allowed"))
    assert job.main([]) == 0
    assert "not_connected" in capsys.readouterr().out


def test_job_rerun_is_idempotent(todo_engine, policy_item):
    seed_todo_graph(todo_engine, policy_item)
    assert job.run_job(todo_engine) == {"processed": 1, "created": 2}
    assert job.run_job(todo_engine) == {"processed": 1, "created": 0}
