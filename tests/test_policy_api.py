import copy
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth_api import auth_api as auth_api
from test_policy_data import batch_for
from test_policy_data import policy_engine as policy_engine
from test_policy_data import policy_item as policy_item
from test_user_profile import profile_api as profile_api

from app.core.db import get_db
from app.main import create_app
from app.models import Policy, PolicyVersion, UserTodo
from app.modules.policies import catalog_service
from app.modules.policies.service import import_policies

TODAY = date(2026, 11, 27)


@pytest.fixture(autouse=True)
def catalog_date(monkeypatch):
    monkeypatch.setattr(catalog_service, "today_kst", lambda: TODAY)


@pytest.fixture
def policy_api(policy_engine):
    application = create_app()

    def override_db():
        with Session(policy_engine) as db, db.begin():
            yield db

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        yield client, policy_engine


def publish(engine, item):
    with Session(engine) as db, db.begin():
        import_policies(db, batch_for(item))
        return db.scalar(select(Policy.id).where(Policy.policy_key == item["policy_key"]))


def test_public_list_details_sources_categories_and_no_writes(policy_api, policy_item):
    client, engine = policy_api
    policy_id = publish(engine, policy_item)
    response = client.get("/api/v1/policies")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1 and page["reference_date"] == str(TODAY)
    assert page["items"][0]["policy_id"] == str(policy_id)
    assert page["items"][0]["is_current"] is True
    detail = client.get(f"/api/v1/policies/{policy_id}").json()
    assert detail["content"] == policy_item["content"]
    assert detail["actions"][0]["action_key"] == policy_item["actions"][0]["action_key"]
    assert (
        "reviewed_by" not in detail and "content_hash" not in detail and "is_example" not in detail
    )
    assert (
        client.get(f"/api/v1/policies/{policy_id}/sources").json()["sources"] == detail["sources"]
    )
    assert len(client.get("/api/v1/policies/categories").json()) == 4
    assert client.get(f"/api/v1/policies/{policy_id}/changes").json()["before"] is None
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(PolicyVersion)) == 1
        assert db.scalar(select(func.count()).select_from(UserTodo)) == 0


def test_filters_never_restore_old_versions_and_hide_future(policy_api, policy_item):
    client, engine = policy_api
    policy_item.update(title="Old unique name", category="transport_card")
    policy_id = publish(engine, policy_item)
    next_item = copy.deepcopy(policy_item)
    next_item.update(
        version=2,
        title="New unique name",
        category="transport_fare",
        effective_from="2026-06-01",
        lifecycle="ended",
        actions=[],
    )
    publish(engine, next_item)
    future = copy.deepcopy(next_item)
    future.update(
        version=3,
        title="Secret future name",
        effective_from="2027-01-01",
        effective_until=None,
        lifecycle="active",
    )
    publish(engine, future)
    assert client.get("/api/v1/policies").json()["total"] == 0
    assert (
        client.get("/api/v1/policies", params={"state": "all", "q": "Old unique name"}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get(
            "/api/v1/policies", params={"state": "all", "category": "transport_card"}
        ).json()["total"]
        == 0
    )
    page = client.get("/api/v1/policies?state=ended").json()
    assert page["total"] == 1 and page["items"][0]["version"] == 2
    assert client.get(f"/api/v1/policies/{policy_id}").json()["version"] == 2
    history = client.get(f"/api/v1/policies/{policy_id}/versions").json()
    assert [row["version"] for row in history["items"]] == [2, 1]
    assert history["items"][1]["state"] == "superseded"
    assert client.get(f"/api/v1/policies/{policy_id}/versions/3").status_code == 404


def test_expiry_boundary_and_same_date_correction(policy_api, policy_item):
    client, engine = policy_api
    policy_item["effective_until"] = str(TODAY)
    policy_id = publish(engine, policy_item)
    assert client.get("/api/v1/policies").json()["total"] == 1
    correction = copy.deepcopy(policy_item)
    correction.update(version=2, effective_until="2026-11-26")
    publish(engine, correction)
    assert client.get("/api/v1/policies").json()["total"] == 0
    assert client.get("/api/v1/policies?state=expired").json()["items"][0]["version"] == 2
    assert client.get(f"/api/v1/policies/{policy_id}").json()["state"] == "expired"


def test_search_is_literal_and_page_total_survives_large_offset(policy_api, policy_item):
    client, engine = policy_api
    policy_item.update(title="Alpha", summary="100%_literal")
    publish(engine, policy_item)
    other = copy.deepcopy(policy_item)
    other.update(policy_key="second-policy", title="Beta", summary="100ZZliteral")
    publish(engine, other)
    assert client.get("/api/v1/policies", params={"q": "%_"}).json()["total"] == 1
    assert client.get("/api/v1/policies", params={"q": "ALPHA"}).json()["total"] == 1
    assert (
        client.get("/api/v1/policies", params={"limit": 1, "offset": 0}).json()["items"][0]["title"]
        == "Alpha"
    )
    page = client.get("/api/v1/policies?offset=100").json()
    assert page["items"] == [] and page["total"] == 2


def test_examples_and_future_only_policies_are_hidden_everywhere(policy_api, policy_item):
    client, engine = policy_api
    example = copy.deepcopy(policy_item)
    example.update(is_example=True)
    example["sources"][0]["kind"] = "example"
    example_id = publish(engine, example)
    future = copy.deepcopy(policy_item)
    future.update(policy_key="future-only", effective_from="2027-01-01", effective_until=None)
    future_id = publish(engine, future)
    assert client.get("/api/v1/policies?state=all").json()["total"] == 0
    for policy_id in (example_id, future_id, uuid4()):
        for suffix in ("", "/sources", "/versions", "/versions/1", "/changes"):
            assert client.get(f"/api/v1/policies/{policy_id}{suffix}").status_code == 404


def test_changes_compare_business_content_not_new_action_ids(policy_api, policy_item):
    client, engine = policy_api
    policy_id = publish(engine, policy_item)
    second = copy.deepcopy(policy_item)
    second["version"] = 2
    publish(engine, second)
    assert client.get(f"/api/v1/policies/{policy_id}/changes").json()["changed_fields"] == []
    third = copy.deepcopy(second)
    third.update(version=3, summary="Changed summary")
    third["actions"][0]["description"] = "Changed instruction"
    publish(engine, third)
    changes = client.get(f"/api/v1/policies/{policy_id}/changes").json()
    assert changes["before"]["version"] == 2 and changes["after"]["version"] == 3
    assert set(changes["changed_fields"]) == {"summary", "actions"}
    historical = client.get(
        f"/api/v1/policies/{policy_id}/changes?from_version=1&to_version=2"
    ).json()
    assert historical["after"]["is_current"] is False
    assert (
        client.get(f"/api/v1/policies/{policy_id}/changes?from_version=3&to_version=2").status_code
        == 422
    )
    assert (
        client.get(f"/api/v1/policies/{policy_id}/changes?from_version=1&to_version=1").status_code
        == 422
    )
    assert client.get(f"/api/v1/policies/{policy_id}/changes?from_version=999").status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=1000001",
        "offset=" + str(2**100),
        "state=planned",
        "category=unknown",
        "q=",
        "q=" + "x" * 101,
        "q=%20%20%20",
    ],
)
def test_invalid_filters(policy_api, query):
    client, _ = policy_api
    response = client.get("/api/v1/policies?" + query)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "details", "request_id"}


def test_personalization_uses_current_owner_and_does_not_generate_todos(
    profile_api, policy_item, monkeypatch
):
    client, engine, _, headers = profile_api
    policy_item["eligibility"].update(requires_confirmation=False, additional_requirements=[])
    policy_id = publish(engine, policy_item)
    missing = client.get("/api/v1/policies/for-me", headers=headers)
    assert missing.status_code == 200 and missing.headers["Cache-Control"] == "no-store"
    assert missing.json()["items"][0]["eligibility_state"] == "unknown"
    client.patch(
        "/api/v1/me", json={"region_code": "seoul", "birth_date": "2000-01-01"}, headers=headers
    )
    eligible = client.get("/api/v1/policies/for-me?eligibility=eligible", headers=headers).json()
    assert eligible["total"] == 1 and eligible["items"][0]["policy_id"] == str(policy_id)
    assert "user_id" not in eligible["items"][0] and "birth_date" not in eligible["items"][0]
    client.patch("/api/v1/me", json={"region_code": "busan"}, headers=headers)
    assert (
        client.get("/api/v1/policies/for-me?eligibility=eligible", headers=headers).json()["total"]
        == 0
    )
    assert (
        client.get("/api/v1/policies/for-me?eligibility=not_eligible", headers=headers).json()[
            "total"
        ]
        == 1
    )
    denied = client.get("/api/v1/policies/for-me")
    assert denied.status_code == 401 and denied.headers["Cache-Control"] == "no-store"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UserTodo)) == 0


def test_personalized_filter_counts_before_pagination(profile_api, policy_item):
    client, engine, _, headers = profile_api
    for index in range(3):
        item = copy.deepcopy(policy_item)
        item["policy_key"] = f"personal-{index}"
        item["eligibility"].update(
            requires_confirmation=False,
            additional_requirements=[],
            region_codes=["seoul"] if index else ["busan"],
        )
        publish(engine, item)
    client.patch(
        "/api/v1/me", json={"region_code": "seoul", "birth_date": "2000-01-01"}, headers=headers
    )
    page = client.get(
        "/api/v1/policies/for-me?eligibility=eligible&limit=1&offset=1", headers=headers
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1


def test_catalog_schema_is_in_openapi_and_reads_reject_writes(policy_api, policy_item):
    client, engine = policy_api
    publish(engine, policy_item)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/policies/categories" in paths and "/api/v1/policies/for-me" in paths
    assert client.post("/api/v1/policies", json=policy_item).status_code == 405
    assert client.get("/api/v1/policies/not-a-uuid").status_code == 422
