"""HTTP flows against migrated, disposable PostgreSQL; no external API calls."""

import copy
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_auth_api import build_client, login, post, register
from test_auth_migrations import postgres_admin as postgres_admin
from test_auth_migrations import postgres_database as postgres_database
from test_auth_postgres import migrated_database as migrated_database
from test_policy_data import policy_item as policy_item

from app.modules.auth import security
from app.modules.chat import client as provider
from app.modules.chat import service as chat_service
from app.modules.chat.config import ChatSettings
from app.modules.chat.schemas import ModelReply
from app.modules.policies.schemas import PolicyImportFile
from app.modules.policies.service import import_policies, today_kst
from scripts.import_policies import load_file


def test_postgres_member_policy_todo_notification_chat_flow(
    migrated_database, monkeypatch, policy_item
):
    engine = migrated_database
    today = today_kst()
    item = copy.deepcopy(policy_item)
    item.update(
        policy_key="integration-only-policy",
        title="Integration-only transport support",
        effective_from=today.isoformat(),
        effective_until=(today + timedelta(days=30)).isoformat(),
        reviewed_on=today.isoformat(),
    )
    item["eligibility"].update(
        age_min=19,
        region_codes=["seoul"],
        transport_cards=[],
        transport_modes=[],
        additional_requirements=[],
        requires_confirmation=False,
    )
    item["actions"][0]["due_date"] = today.isoformat()
    with Session(engine) as db, db.begin():
        import_policies(db, PolicyImportFile(schema_version=1, policies=[item]))

    monkeypatch.setattr(
        chat_service,
        "get_chat_settings",
        lambda: ChatSettings(
            _env_file=None, gemini_api_key="integration-test-only", gemini_model="gemini-test"
        ),
    )
    monkeypatch.setattr(chat_service, "limiter", chat_service.ChatLimiter())
    generate = Mock()
    monkeypatch.setattr(provider, "generate", generate)
    app = build_client(engine, monkeypatch)
    with TestClient(app) as owner, TestClient(app) as other:
        assert register(owner, "integration-owner@example.com").status_code == 201
        assert register(other, "integration-other@example.com").status_code == 201
        grant = login(owner, "integration-owner@example.com").json()
        other_grant = login(other, "integration-other@example.com").json()
        headers = {"Authorization": f"Bearer {grant['access_token']}"}
        other_headers = {"Authorization": f"Bearer {other_grant['access_token']}"}
        owner.headers.update(headers)
        other.headers.update(other_headers)
        assert owner.get("/api/v1/auth/me").status_code == 200
        saved = owner.patch(
            "/api/v1/me",
            json={
                "birth_date": "2000-01-01",
                "region_code": "seoul",
                "transport_cards": ["k_pass"],
                "transport_modes": ["bus"],
            },
        )
        assert saved.status_code == 200 and saved.json()["is_complete"]
        assert other.get("/api/v1/me").json()["region_code"] is None
        catalog = owner.get("/api/v1/policies").json()
        assert catalog["total"] == 1
        policy_id = catalog["items"][0]["policy_id"]
        version_id = catalog["items"][0]["version_id"]
        assert owner.get(f"/api/v1/policies/{policy_id}").status_code == 200
        assert (
            owner.get("/api/v1/policies/for-me").json()["items"][0]["eligibility_state"]
            == "eligible"
        )
        assert (
            other.get("/api/v1/policies/for-me").json()["items"][0]["eligibility_state"]
            == "unknown"
        )

        assert owner.post("/api/v1/todos/sync", json={}).json()["created"] == 1
        assert owner.post("/api/v1/todos/sync", json={}).json()["created"] == 0
        todo_id = owner.get("/api/v1/todos").json()["items"][0]["id"]
        assert other.get("/api/v1/todos").json()["total"] == 0
        assert other.get(f"/api/v1/todos/{todo_id}").status_code == 404
        assert other.patch(f"/api/v1/todos/{todo_id}", json={"completed": True}).status_code == 404

        assert owner.post("/api/v1/notifications/sync", json={}).json()["created"] == 2
        assert owner.post("/api/v1/notifications/sync", json={}).json()["created"] == 0
        assert owner.get("/api/v1/notifications/unread-count").json()["count"] == 2
        notification = owner.get("/api/v1/notifications").json()["items"][0]
        assert (
            other.post(f"/api/v1/notifications/{notification['id']}/read", json={}).status_code
            == 404
        )
        assert other.get("/api/v1/notifications/unread-count").json()["count"] == 0
        assert owner.post("/api/v1/notifications/read-all", json={}).json()["updated"] == 2
        assert owner.post("/api/v1/notifications/read-all", json={}).json()["updated"] == 0

        created = owner.post("/api/v1/chat/conversations", json={})
        assert created.status_code == 201
        conversation_id = created.json()["id"]
        path = f"/api/v1/chat/conversations/{conversation_id}/messages"
        generate.return_value = ModelReply(
            answer="Check the cited policy.",
            references=[{"version_id": version_id, "source_key": item["sources"][0]["source_key"]}],
            needs_more_info=False,
        )
        body = {
            "request_id": str(uuid4()),
            "question": "Transport support?",
            "policy_ids": [policy_id],
        }
        message = owner.post(path, json=body)
        assert message.status_code == 201
        assert message.json()["related_todos"][0]["id"] == todo_id
        assert message.json()["sources"] and message.json()["external_used"]
        assert owner.post(path, json=body).json()["id"] == message.json()["id"]
        assert generate.call_count == 1
        assert other.get(path).status_code == 404
        assert other.post(path, json=body).status_code == 404
        assert (
            owner.patch(f"/api/v1/todos/{todo_id}", json={"completed": True}).json()["status"]
            == "completed"
        )
        assert owner.get("/api/v1/todos/summary").json()["completed"] == 1

        assert post(owner, "refresh", csrf="invalid-csrf").status_code == 403
        assert (
            post(
                owner, "refresh", csrf=grant["csrf_token"], origin="https://invalid.example"
            ).status_code
            == 403
        )
        refreshed = post(owner, "refresh", csrf=grant["csrf_token"])
        assert refreshed.status_code == 200
        token = refreshed.json()["access_token"]
        owner.headers["Authorization"] = f"Bearer {token}"
        assert owner.get("/api/v1/me").status_code == 200
        real_now = security.now_utc()
        with monkeypatch.context() as expired:
            expired.setattr(security, "now_utc", lambda: real_now + timedelta(days=8))
            assert owner.get("/api/v1/me").status_code == 401
        assert post(owner, "logout", csrf=grant["csrf_token"]).status_code == 204
        for endpoint in (
            "auth/me",
            "me",
            "policies/for-me",
            "todos",
            "notifications",
            "chat/conversations",
        ):
            assert owner.get(f"/api/v1/{endpoint}").status_code == 401
        assert other.get("/api/v1/auth/me").status_code == 200


def test_reviewed_k_pass_requires_confirmation_without_creating_todos(
    migrated_database, monkeypatch
):
    engine = migrated_database
    with Session(engine) as db, db.begin():
        import_policies(db, load_file(Path("data/policies/k-pass.v1.json")))
    with TestClient(build_client(engine, monkeypatch)) as client:
        assert register(client).status_code == 201
        grant = login(client).json()
        client.headers["Authorization"] = f"Bearer {grant['access_token']}"
        result = client.get("/api/v1/policies/for-me")
        assert result.status_code == 200
        assert result.json()["items"][0]["eligibility_state"] == "unknown"
        assert client.post("/api/v1/todos/sync", json={}).json()["created"] == 0
        assert client.post("/api/v1/notifications/sync", json={}).json()["created"] == 0
