import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from uuid import uuid4

import boso_ai.llm_client as ai_client
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth_api import auth_api as auth_api
from test_policy_data import policy_item as policy_item
from test_todos import TODAY, seed_policy, seed_todo_graph
from test_todos import todo_date as todo_date
from test_todos import todo_engine as todo_engine
from test_user_profile import profile_api as profile_api

from app.core.errors import AppError
from app.models import ChatTurn, PolicyVersion
from app.modules.chat import client, service
from app.modules.chat.config import ChatSettings
from app.modules.chat.schemas import ConversationCreate, ModelReply, TurnRequest


@pytest.fixture
def provider_payload():
    return {
        "question": "가상 정책 안내를 확인하고 싶어요.",
        "conversation": [],
        "policies": [
            {
                "version_id": str(uuid4()),
                "title": "가상 정책",
                "summary": "가상 안내",
                "content": "직접 작성한 테스트 자료입니다.",
                "state": "active",
                "effective_from": "2026-11-01",
                "effective_until": None,
                "assessment": {"state": "eligible", "reasons": []},
                "actions": [],
                "source_keys": ["test_notice"],
            }
        ],
    }


@pytest.fixture
def chat_graph(todo_engine, policy_item, monkeypatch):
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    owner, policy_id, todo_id, _ = seed_todo_graph(todo_engine, policy_item)
    with Session(todo_engine) as db, db.begin():
        conversation = service.create_conversation(db, owner, ConversationCreate())
        version_id = db.scalar(select(PolicyVersion.id))
    settings = ChatSettings(
        _env_file=None, gemini_api_key="test-only-gemini-key", gemini_model="gemini-test"
    )
    monkeypatch.setattr(service, "get_chat_settings", lambda: settings)
    monkeypatch.setattr(service, "limiter", service.ChatLimiter())
    reply = ModelReply(
        answer="테스트 정책 근거를 확인해주세요.",
        references=[{"version_id": version_id, "source_key": "example-source"}],
        needs_more_info=False,
    )
    fake = Mock(return_value=reply)
    monkeypatch.setattr(client, "generate", fake)
    return todo_engine, owner, policy_id, todo_id, conversation.id, version_id, fake


def test_grounded_turn_repeat_and_related_owned_todos(chat_graph):
    engine, owner, policy_id, todo_id, conversation_id, _, fake = chat_graph
    body = TurnRequest(request_id=uuid4(), question="정책 알려줘", policy_ids=[policy_id])
    with Session(engine) as db, db.begin():
        response = service.send_message(db, owner, conversation_id, body)
        assert response.sources[0].url == "https://example.invalid/policy"
        assert response.related_todos[0].id == todo_id
        assert response.external_used and not response.needs_more_info
        assert service.send_message(db, owner, conversation_id, body).id == response.id
        assert fake.call_count == 1
        body.question = "다른 질문"
        with pytest.raises(AppError) as error:
            service.send_message(db, owner, conversation_id, body)
        assert error.value.code == "CHAT_REQUEST_CONFLICT"
        assert service.list_turns(db, owner, conversation_id).total == 1
        payload = fake.call_args.args[1]
        encoded = json.dumps(payload)
        assert str(owner) not in encoded and "todo@example.invalid" not in encoded
        assert "birth_date" not in encoded and "user_id" not in encoded


def test_missing_policies_do_not_call_provider(todo_engine, monkeypatch):
    from test_todos import seed_user

    monkeypatch.setattr(client, "generate", lambda *args: pytest.fail("Must not call external API"))
    with Session(todo_engine) as db, db.begin():
        owner = seed_user(db)
        conversation = service.create_conversation(db, owner, ConversationCreate())
        response = service.send_message(
            db, owner, conversation.id, TurnRequest(request_id=uuid4(), question="안녕하세요")
        )
        assert response.needs_more_info and not response.external_used and response.sources == []


def test_fake_citations_are_replaced_by_safe_fallback(chat_graph):
    engine, owner, policy_id, _, conversation_id, _, fake = chat_graph
    fake.return_value = ModelReply(
        answer="invented",
        references=[{"version_id": uuid4(), "source_key": "fake"}],
        needs_more_info=False,
    )
    with Session(engine) as db, db.begin():
        response = service.send_message(
            db,
            owner,
            conversation_id,
            TurnRequest(request_id=uuid4(), question="질문", policy_ids=[policy_id]),
        )
        assert (
            response.answer == service.FALLBACK
            and response.sources == []
            and response.needs_more_info
        )


def test_provider_error_rolls_back_turn(chat_graph):
    engine, owner, policy_id, _, conversation_id, _, fake = chat_graph
    fake.side_effect = AppError(503, "CHAT_PROVIDER_UNAVAILABLE", "잠시 후 다시 요청해주세요.")
    with pytest.raises(AppError), Session(engine) as db, db.begin():
        service.send_message(
            db,
            owner,
            conversation_id,
            TurnRequest(request_id=uuid4(), question="질문", policy_ids=[policy_id]),
        )
    with Session(engine) as db:
        assert db.scalars(select(ChatTurn)).all() == []


def test_conversation_owner_is_enforced(chat_graph):
    engine, _, policy_id, _, conversation_id, _, fake = chat_graph
    with Session(engine) as db:
        for call in (
            lambda: service.list_turns(db, uuid4(), conversation_id),
            lambda: service.send_message(
                db,
                uuid4(),
                conversation_id,
                TurnRequest(request_id=uuid4(), question="질문", policy_ids=[policy_id]),
            ),
        ):
            with pytest.raises(AppError) as error:
                call()
            assert error.value.code == "CHAT_NOT_FOUND"
        assert not fake.called


def test_chat_api_validation_and_private_cache(profile_api):
    client_api, _, _, headers = profile_api
    created = client_api.post("/api/v1/chat/conversations", json={}, headers=headers)
    assert created.status_code == 201 and created.headers["Cache-Control"] == "no-store"
    conversation_id = created.json()["id"]
    body = {"request_id": str(uuid4()), "question": "안녕하세요"}
    response = client_api.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages", json=body, headers=headers
    )
    assert response.status_code == 201 and response.json()["external_used"] is False
    assert client_api.get("/api/v1/chat/conversations", headers=headers).json()["total"] == 1
    assert (
        client_api.get(
            f"/api/v1/chat/conversations/{conversation_id}/messages", headers=headers
        ).json()["total"]
        == 1
    )
    assert client_api.get("/api/v1/chat/conversations").status_code == 401
    assert (
        client_api.post(
            "/api/v1/chat/conversations", json={"user_id": str(uuid4())}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client_api.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={**body, "question": " " * 3},
            headers=headers,
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "failure,code",
    [
        (
            HTTPError("https://example.invalid", 429, "secret", {}, BytesIO(b"secret")),
            "CHAT_PROVIDER_RATE_LIMITED",
        ),
        (
            HTTPError("https://example.invalid", 302, "secret", {}, BytesIO(b"secret")),
            "CHAT_PROVIDER_UNAVAILABLE",
        ),
        (URLError("secret"), "CHAT_PROVIDER_UNAVAILABLE"),
        (TimeoutError("secret"), "CHAT_PROVIDER_UNAVAILABLE"),
        (b"secret invalid JSON", "CHAT_PROVIDER_INVALID_RESPONSE"),
    ],
)
def test_provider_errors_never_expose_internal_values(monkeypatch, failure, code, provider_payload):
    class Opener:
        def open(self, *args, **kwargs):
            if isinstance(failure, bytes):
                return BytesIO(failure)
            raise failure

    monkeypatch.setattr(ai_client, "build_opener", lambda *args: Opener())
    settings = ChatSettings(_env_file=None, gemini_api_key="secret-key", gemini_model="gemini-test")
    with pytest.raises(AppError) as error:
        client.generate(settings, provider_payload)
    assert error.value.code == code
    assert "secret" not in error.value.message


@pytest.mark.parametrize("max_output_tokens", [128, 1024, 2048])
def test_provider_request_uses_fixed_tls_host_header_and_bounded_json(
    monkeypatch, provider_payload, max_output_tokens
):
    body = json.dumps(
        {
            "answer": "ok",
            "references": [
                {
                    "version_id": provider_payload["policies"][0]["version_id"],
                    "source_key": "test_notice",
                }
            ],
            "needs_more_info": True,
        }
    )
    raw = json.dumps(
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": body}]}}]}
    ).encode()
    response = BytesIO(raw)

    def open_request(request, timeout):
        assert (
            request.full_url
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
        )
        assert "secret-key" not in request.full_url
        assert request.get_header("X-goog-api-key") == "secret-key"
        assert 0 < timeout <= 10
        assert json.loads(request.data)["generationConfig"]["maxOutputTokens"] == max_output_tokens
        return response

    monkeypatch.setattr(ai_client, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    settings = ChatSettings(
        _env_file=None,
        gemini_api_key="secret-key",
        gemini_model="gemini-test",
        gemini_max_output_tokens=max_output_tokens,
    )
    assert client.generate(settings, provider_payload).answer == "ok"


def test_rate_limit_is_bounded_and_enforced():
    limiter = service.ChatLimiter()
    for _ in range(10):
        limiter.check("user")
    with pytest.raises(AppError) as error:
        limiter.check("user")
    assert error.value.status == 429
    for _ in range(4100):
        limiter.check(uuid4())
    assert len(limiter.entries) == 4096


def test_chat_api_uses_installed_ai_once_and_preserves_rollback(
    profile_api, policy_item, monkeypatch
):
    client_api, engine, _, headers = profile_api
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    monkeypatch.setattr(service, "limiter", service.ChatLimiter())
    settings = ChatSettings(_env_file=None, gemini_api_key="test-only", gemini_model="gemini-test")
    monkeypatch.setattr(service, "get_chat_settings", lambda: settings)
    assert (
        client_api.patch(
            "/api/v1/me", json={"birth_date": "2000-01-01", "region_code": "seoul"}, headers=headers
        ).status_code
        == 200
    )
    with Session(engine) as db, db.begin():
        _, policy_id = seed_policy(db, policy_item)
    assert client_api.post("/api/v1/todos/sync", json={}, headers=headers).status_code == 200
    requests = []
    fail_provider = False

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if fail_provider:
                raise HTTPError("https://example.invalid", 503, "secret", {}, BytesIO(b"secret"))
            sent = json.loads(json.loads(request.data)["contents"][0]["parts"][0]["text"])
            assert "birth_date" not in json.dumps(sent)
            policy = sent["policies"][0]
            answer = {
                "answer": "가상 테스트 정책의 확인 절차입니다.",
                "references": [
                    {"version_id": policy["version_id"], "source_key": policy["source_keys"][0]}
                ],
                "needs_more_info": False,
            }
            return BytesIO(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {"parts": [{"text": json.dumps(answer)}]},
                            }
                        ]
                    }
                ).encode()
            )

    monkeypatch.setattr(ai_client, "build_opener", lambda *args: Opener())
    conversation = client_api.post("/api/v1/chat/conversations", json={}, headers=headers).json()
    url = f"/api/v1/chat/conversations/{conversation['id']}/messages"
    body = {
        "request_id": str(uuid4()),
        "question": "가상 정책 안내",
        "policy_ids": [str(policy_id)],
    }
    first = client_api.post(url, json=body, headers=headers)
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["external_used"]
    assert result["sources"][0]["url"] == "https://example.invalid/policy"
    assert result["related_todos"][0]["policy_id"] == str(policy_id)
    repeated = client_api.post(url, json=body, headers=headers)
    assert repeated.json()["id"] == result["id"]
    assert len(requests) == 1
    fail_provider = True
    failed = client_api.post(url, json={**body, "request_id": str(uuid4())}, headers=headers)
    assert failed.status_code == 503
    assert failed.json()["code"] == "CHAT_PROVIDER_UNAVAILABLE"
    assert "secret" not in failed.text
    assert len(requests) == 2
    assert client_api.get(url, headers=headers).json()["total"] == 1
