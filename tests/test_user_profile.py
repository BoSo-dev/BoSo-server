from datetime import UTC, date, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from test_auth_api import EMAIL, login, register
from test_auth_api import auth_api as auth_api

from app.core.errors import AppError
from app.models import AuthSession, User, UserProfile, UserTransportCard, UserTransportMode
from app.modules.users import service

TODAY = date(2026, 11, 27)
BODY = {
    "birth_date": "2000-11-28",
    "region_code": "seoul",
    "transport_cards": ["k_pass"],
    "transport_modes": ["bus", "subway"],
}


@pytest.fixture
def profile_api(auth_api, monkeypatch):
    client, engine, application = auth_api
    monkeypatch.setattr(service, "today_kst", lambda: TODAY)
    assert register(client).status_code == 201
    token = login(client).json()["access_token"]
    return client, engine, application, {"Authorization": f"Bearer {token}"}


def get(client, headers):
    return client.get("/api/v1/me", headers=headers)


def update(client, headers, body):
    return client.patch("/api/v1/me", json=body, headers=headers)


def test_unregistered_profile_is_read_only_and_incomplete(profile_api):
    client, engine, _, headers = profile_api
    response = get(client, headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == EMAIL
    assert data["reference_date"] == TODAY.isoformat()
    assert data["birth_date"] is None and data["age"] is None
    assert data["region_code"] is None and data["updated_at"] is None
    assert data["transport_cards"] == data["transport_modes"] == []
    assert data["is_complete"] is False
    assert set(data["missing_fields"]) == set(BODY)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 0


def test_register_read_edit_and_clear_transport_profile(profile_api):
    client, engine, _, headers = profile_api
    response = update(client, headers, BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["age"] == 25
    assert data["is_complete"] is True and data["missing_fields"] == []
    assert data["updated_at"] is not None
    assert get(client, headers).json() == data
    changed = update(
        client, headers, {"region_code": "gyeonggi", "transport_cards": ["k_pass", "climate_card"]}
    )
    assert changed.json()["birth_date"] == BODY["birth_date"]
    assert changed.json()["transport_modes"] == BODY["transport_modes"]
    assert changed.json()["transport_cards"] == ["climate_card", "k_pass"]
    fallback = update(client, headers, {"transport_cards": ["other_or_none"]})
    assert fallback.status_code == 200 and fallback.json()["is_complete"] is True
    clear = update(
        client,
        headers,
        {"birth_date": None, "region_code": None, "transport_cards": [], "transport_modes": []},
    )
    assert clear.status_code == 200 and clear.json()["is_complete"] is False
    assert clear.json()["age"] is None
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 1
        assert db.scalar(select(func.count()).select_from(UserTransportCard)) == 0
        assert db.scalar(select(func.count()).select_from(UserTransportMode)) == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"user_id": str(uuid4())},
        {"email": "change@example.com"},
        {"age": 20},
        {"is_active": True},
        {"password_hash": "not-allowed"},
        {"region_code": "invalid"},
        {"region_code": "SEOUL"},
        {"transport_cards": None},
        {"transport_cards": "k_pass"},
        {"transport_cards": ["unknown"]},
        {"transport_cards": ["k_pass", "k_pass"]},
        {"transport_cards": ["other_or_none", "k_pass"]},
        {"transport_modes": None},
        {"transport_modes": ["bus", "bus"]},
        {"transport_modes": ["walk"]},
        {"transport_modes": "bus"},
        {"birth_date": 946684800},
        {"birth_date": True},
        {"birth_date": "2000-01-01T00:00:00Z"},
        {"birth_date": "2000-1-1"},
        {"birth_date": "2025-02-29"},
        {"birth_date": "1899-12-31"},
        {"birth_date": "2026-11-28"},
    ],
)
def test_invalid_input_is_rejected_without_writes(profile_api, body):
    client, engine, _, headers = profile_api
    response = update(client, headers, body)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "details", "request_id"}
    assert response.headers["Cache-Control"] == "no-store"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 0


@pytest.mark.parametrize("birth_date", ["1900-01-01", TODAY.isoformat(), "2000-02-29"])
def test_birth_date_boundaries(profile_api, birth_date):
    client, _, _, headers = profile_api
    response = update(client, headers, {"birth_date": birth_date})
    assert response.status_code == 200
    assert response.json()["birth_date"] == birth_date


@pytest.mark.parametrize(
    ("birth", "on", "age"),
    [
        ("2000-11-28", "2026-11-27", 25),
        ("2000-11-28", "2026-11-28", 26),
        ("2000-02-29", "2025-02-28", 24),
        ("2000-02-29", "2025-03-01", 25),
    ],
)
def test_age_is_calculated_at_reference_date(birth, on, age):
    assert service.age_on(date.fromisoformat(birth), date.fromisoformat(on)) == age


def test_profile_options_match_revised_screen(profile_api):
    client, _, _, headers = profile_api
    response = client.get("/api/v1/me/options", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["regions"]) == 17
    assert {c["code"] for c in data["transport_cards"]} == {
        "k_pass",
        "climate_card",
        "other_or_none",
    }
    assert {m["code"] for m in data["transport_modes"]} == {"bus", "subway"}


@pytest.mark.parametrize("method", ["GET", "PATCH", "OPTIONS_ENDPOINT"])
def test_profile_requires_authentication(auth_api, method):
    client, _, _ = auth_api
    if method == "PATCH":
        response = client.patch("/api/v1/me", json=BODY)
    else:
        response = client.get(
            "/api/v1/me/options" if method == "OPTIONS_ENDPOINT" else "/api/v1/me"
        )
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_users_cannot_read_or_modify_another_profile(profile_api):
    client, engine, application, first_headers = profile_api
    first = update(client, first_headers, BODY).json()
    with TestClient(application) as other:
        assert register(other, "other@example.com").status_code == 201
        token = login(other, "other@example.com").json()["access_token"]
        other_headers = {"Authorization": f"Bearer {token}"}
        current = other.get(
            "/api/v1/me", params={"user_id": first["user_id"]}, headers=other_headers
        )
        assert current.json()["user_id"] != first["user_id"]
        assert current.json()["birth_date"] is None
        assert (
            update(
                other, other_headers, {"user_id": first["user_id"], "region_code": "busan"}
            ).status_code
            == 422
        )
        assert other.get(f"/api/v1/me/{first['user_id']}", headers=other_headers).status_code == 404
        assert update(other, other_headers, {"region_code": "busan"}).status_code == 200
    assert get(client, first_headers).json()["region_code"] == "seoul"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 2


def test_revoked_or_inactive_user_cannot_update(profile_api):
    client, engine, _, headers = profile_api
    with Session(engine) as db:
        session = db.scalar(select(AuthSession))
        session.revoked_at = datetime.now(UTC)
        session.revocation_reason = "logout"
        db.commit()
    assert update(client, headers, BODY).status_code == 401
    assert get(client, headers).status_code == 401


def test_personalization_context_excludes_email_and_full_birth_date(profile_api):
    client, engine, _, headers = profile_api
    user_id = update(client, headers, BODY).json()["user_id"]
    from uuid import UUID

    with Session(engine) as db:
        context = service.get_personalization_context(db, UUID(user_id), reference_date=TODAY)
        assert context.age == 25 and context.region_code == "seoul"
        assert "email" not in context.model_dump() and "birth_date" not in context.model_dump()
        assert context.is_complete
        with pytest.raises(AppError) as error:
            service.get_personalization_context(db, uuid4())
        assert error.value.status == 404
        db.get(User, UUID(user_id)).is_active = False
        db.flush()
        with pytest.raises(AppError):
            service.get_personalization_context(db, UUID(user_id))


def test_context_for_missing_profile_does_not_assume_eligibility(profile_api):
    client, engine, _, headers = profile_api
    from uuid import UUID

    user_id = UUID(get(client, headers).json()["user_id"])
    with Session(engine) as db:
        context = service.get_personalization_context(db, user_id, reference_date=TODAY)
        assert not context.is_complete
        assert context.age is None and context.region_code is None
        assert len(context.missing_fields) == 4


def test_context_before_birth_does_not_provide_negative_age(profile_api):
    client, engine, _, headers = profile_api
    from uuid import UUID

    user_id = UUID(update(client, headers, BODY).json()["user_id"])
    with Session(engine) as db:
        context = service.get_personalization_context(db, user_id, reference_date=date(1999, 1, 1))
        assert context.age is None and not context.is_complete
        assert "birth_date" in context.missing_fields


def test_repeated_list_replacement_is_idempotent(profile_api):
    client, engine, _, headers = profile_api
    for _ in range(3):
        assert update(client, headers, BODY).status_code == 200
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserTransportCard)) == 1
        assert db.scalar(select(func.count()).select_from(UserTransportMode)) == 2


def test_profile_and_lists_are_read_with_one_statement(profile_api):
    client, engine, _, headers = profile_api
    assert (
        update(client, headers, {**BODY, "transport_cards": ["k_pass", "climate_card"]}).status_code
        == 200
    )
    queries = []

    def count_queries(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement.split()[0].upper())

    with Session(engine) as db:
        user = db.scalar(select(User))
        event.listen(engine, "before_cursor_execute", count_queries)
        try:
            result = service.read_profile(db, user)
        finally:
            event.remove(engine, "before_cursor_execute", count_queries)
    assert queries == ["SELECT"]
    assert result.region_code == BODY["region_code"]
    assert result.transport_cards == ["climate_card", "k_pass"]
    assert result.transport_modes == ["bus", "subway"]


def test_commit_failure_rolls_back_existing_profile_and_lists(profile_api):
    client, engine, _, headers = profile_api
    assert update(client, headers, BODY).status_code == 200

    class FailedCommit(Session):
        def commit(self):
            raise OperationalError("commit", {}, Exception("test-only-driver-secret"))

    with patch(
        "app.core.db.sessionmaker", lambda *a, **kw: sessionmaker(*a, class_=FailedCommit, **kw)
    ):
        response = update(
            client,
            headers,
            {"region_code": "busan", "transport_cards": ["climate_card"], "transport_modes": []},
        )
    assert response.status_code == 500
    assert "test-only-driver-secret" not in response.text
    current = get(client, headers).json()
    for key in BODY:
        assert current[key] == BODY[key]


def test_first_insert_failure_leaves_no_profile(profile_api):
    client, engine, _, headers = profile_api

    class FailedCommit(Session):
        def commit(self):
            raise OperationalError("commit", {}, Exception("test-only-driver-secret"))

    with patch(
        "app.core.db.sessionmaker", lambda *a, **kw: sessionmaker(*a, class_=FailedCommit, **kw)
    ):
        assert update(client, headers, BODY).status_code == 500
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 0


def test_sensitive_profile_values_are_not_logged(profile_api, caplog):
    client, _, _, headers = profile_api
    update(client, headers, BODY)
    get(client, headers)
    assert BODY["birth_date"] not in caplog.text and EMAIL not in caplog.text
    assert headers["Authorization"] not in caplog.text


@pytest.mark.parametrize("violation", ["region", "date", "card", "mode", "duplicate", "parent"])
def test_database_profile_constraints(profile_api, violation):
    client, engine, _, headers = profile_api
    from uuid import UUID

    user_id = UUID(update(client, headers, BODY).json()["user_id"])
    with Session(engine) as db:
        if violation in {"region", "date"}:
            profile = db.get(UserProfile, user_id)
            if violation == "region":
                profile.region_code = "unknown"
            else:
                profile.birth_date = date(1899, 1, 1)
        elif violation == "mode":
            db.add(UserTransportMode(user_id=user_id, mode_code="unknown"))
        else:
            db.add(
                UserTransportCard(
                    user_id=uuid4() if violation == "parent" else user_id,
                    card_code="unknown" if violation == "card" else "k_pass",
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("parent", [User, UserProfile])
def test_database_profile_delete_cascades(profile_api, parent):
    client, engine, _, headers = profile_api
    from uuid import UUID

    user_id = UUID(update(client, headers, BODY).json()["user_id"])
    with Session(engine) as db:
        db.execute(
            delete(parent).where((parent.id if parent is User else parent.user_id) == user_id)
        )
        db.commit()
        for table in (UserProfile, UserTransportCard, UserTransportMode):
            assert db.scalar(select(func.count()).select_from(table)) == 0
