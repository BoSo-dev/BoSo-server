from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError
from app.main import create_app


def test_liveness_and_request_id(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["X-Request-ID"])


def test_readiness_queries_database(client):
    assert client.get("/health/ready").status_code == 200


def test_readiness_failure_hides_connection_details():
    application = create_app()
    db = Mock()
    db.execute.side_effect = OperationalError("secret-host", {}, Exception("secret-password"))
    application.dependency_overrides[get_db] = lambda: db
    with TestClient(application) as client:
        response = client.get("/health/ready", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "secret" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unknown_route_uses_error_contract(client):
    response = client.get("/missing")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "details", "request_id"}


def test_validation_errors_do_not_echo_input():
    application = create_app()

    @application.get("/validate")
    def validate(value: int):
        return value

    with TestClient(application) as client:
        response = client.get("/validate", params={"value": "secret-password"})
    assert response.status_code == 422
    assert "secret-password" not in response.text
    assert response.json()["details"][0]["loc"] == ["query", "value"]


def test_unhandled_exception_is_sanitized():
    application = create_app()

    @application.get("/explode")
    def explode():
        raise RuntimeError("secret-password")

    with TestClient(application) as client:
        response = client.get("/explode", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secret-password" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_business_error_contract():
    application = create_app()

    @application.get("/conflict")
    def conflict():
        raise AppError(409, "CONFLICT", "이미 존재합니다.")

    with TestClient(application) as client:
        response = client.get("/conflict")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_database_url_is_redacted():
    settings = Settings(_env_file=None, database_url="postgresql://user:secret@host/db")
    assert "secret" not in repr(settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"cors_origins": ["*"]},
        {"database_url": "sqlite:///test.db"},
        {"database_url": "mysql://localhost/test"},
    ],
)
def test_production_configuration_rejects_invalid_defaults(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", **overrides)
