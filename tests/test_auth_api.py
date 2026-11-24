from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import Base, make_engine
from app.core.dependencies import DbSession
from app.main import create_app
from app.models import AuthSession, RefreshToken, User
from app.modules.auth import security
from app.modules.auth.dependencies import CurrentUser

ORIGIN = "http://localhost:3000"
PASSWORD = "test-only-very-long-password"
EMAIL = "member@example.com"


def configure_auth_test(monkeypatch, url):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", str(url))
    monkeypatch.setenv("MIGRATION_DATABASE_URL", str(url))
    monkeypatch.setenv("AUTH_JWT_KEY", "test-only-jwt-" + "a" * 48)
    monkeypatch.setenv("AUTH_CSRF_KEY", "test-only-csrf-" + "b" * 48)
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    get_settings.cache_clear()


def build_client(engine, monkeypatch):
    monkeypatch.setattr("app.core.db.get_engine", lambda: engine)
    application = create_app()

    @application.get("/test-owner/{user_id}")
    def owner(user_id: str, user: CurrentUser, db: DbSession):
        # Demonstrate the contract provided to other modules, never accept a
        # caller-supplied identifier as the authenticated user.
        return {"authenticated_id": str(user.id)}

    return application


@pytest.fixture
def auth_api(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'auth-api.db'}"
    configure_auth_test(monkeypatch, url)
    engine = make_engine(url)
    Base.metadata.create_all(engine)  # Disposable test DB only, never application startup.
    application = build_client(engine, monkeypatch)
    try:
        with TestClient(application) as client:
            yield client, engine, application
    finally:
        engine.dispose()
        get_settings.cache_clear()


def post(client, path, body=None, *, csrf=None, origin=ORIGIN, **kwargs):
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    return client.post(f"/api/v1/auth/{path}", json=body, headers=headers, **kwargs)


def register(client, email=EMAIL):
    return post(client, "signup", {"email": email, "password": PASSWORD})


def login(client, email=EMAIL):
    return post(client, "login", {"email": email, "password": PASSWORD})


def me(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_signup_login_me_refresh_logout_roundtrip(auth_api):
    client, engine, _ = auth_api
    registered = register(client, " MEMBER@EXAMPLE.COM ")
    assert registered.status_code == 201
    assert registered.json()["email"] == EMAIL
    assert set(registered.json()) == {"id", "email", "is_active", "created_at"}
    assert "set-cookie" not in registered.headers
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and 899 <= body["expires_in"] <= 900
    assert me(client, body["access_token"]).json()["id"] == registered.json()["id"]
    old_refresh = client.cookies.get("boso-dev-refresh")
    refreshed = post(client, "refresh", csrf=body["csrf_token"])
    assert refreshed.status_code == 200
    assert client.cookies.get("boso-dev-refresh") != old_refresh
    assert refreshed.json()["session_expires_at"] == body["session_expires_at"]
    assert refreshed.json()["csrf_token"] == body["csrf_token"]
    with Session(engine) as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        tokens = db.scalars(select(RefreshToken)).all()
        assert len(tokens) == 2
        assert sum(t.used_at is None for t in tokens) == 1
        assert all(old_refresh != t.token_hash for t in tokens)
        assert security.refresh_hash(old_refresh) in {t.token_hash for t in tokens}
    logged_out = post(client, "logout", csrf=body["csrf_token"])
    assert logged_out.status_code == 204 and logged_out.content == b""
    assert client.cookies.get("boso-dev-refresh") is None
    assert me(client, body["access_token"]).status_code == 401
    assert me(client, refreshed.json()["access_token"]).status_code == 401


def test_duplicate_signup_and_wrong_login_are_safe(auth_api):
    client, _, _ = auth_api
    assert register(client).status_code == 201
    assert register(client, EMAIL.upper()).status_code == 409
    wrong = post(client, "login", {"email": EMAIL, "password": PASSWORD + "wrong"})
    absent = login(client, "absent@example.com")
    assert wrong.status_code == absent.status_code == 401
    assert wrong.json()["message"] == absent.json()["message"]
    assert PASSWORD not in wrong.text


@pytest.mark.parametrize("path", ["signup", "login", "refresh", "logout", "csrf"])
@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", ORIGIN + ".evil.example"])
def test_browser_auth_rejects_missing_or_untrusted_origin(auth_api, path, origin):
    client, _, _ = auth_api
    response = post(client, path, {"email": EMAIL, "password": PASSWORD}, origin=origin)
    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"
    assert response.headers["Cache-Control"] == "no-store"


def test_browser_auth_requires_json_and_csrf(auth_api):
    client, _, _ = auth_api
    form = client.post(
        "/api/v1/auth/login", content="email=test&password=test", headers={"Origin": ORIGIN}
    )
    assert form.status_code == 415
    register(client)
    body = login(client).json()
    for path in ("refresh", "logout"):
        assert post(client, path).status_code == 403
        assert post(client, path, csrf=body["csrf_token"] + "wrong").status_code == 403
    assert me(client, body["access_token"]).status_code == 200


def test_csrf_bootstrap_for_page_reload_and_cross_host_frontend(auth_api):
    client, _, _ = auth_api
    register(client)
    body = login(client).json()
    response = post(client, "csrf")
    assert response.json()["csrf_token"] == body["csrf_token"]
    client.cookies.delete("boso-dev-csrf")
    renewed = post(client, "csrf")
    assert renewed.status_code == 200
    assert post(client, "refresh", csrf=renewed.json()["csrf_token"]).status_code == 200


def test_refresh_reuse_revocation_commits_before_401(auth_api):
    client, engine, _ = auth_api
    register(client)
    body = login(client).json()
    old = client.cookies.get("boso-dev-refresh")
    assert post(client, "refresh", csrf=body["csrf_token"]).status_code == 200
    client.cookies.set("boso-dev-refresh", old, domain="testserver.local", path="/")
    denied = post(client, "refresh", csrf=body["csrf_token"])
    assert denied.status_code == 401
    assert denied.headers["WWW-Authenticate"] == "Bearer"
    assert client.cookies.get("boso-dev-refresh") is None
    with Session(engine) as db:
        session = db.scalar(select(AuthSession))
        assert session.revoked_at is not None
        assert session.revocation_reason == "refresh_reuse"
    assert me(client, body["access_token"]).status_code == 401


def test_logout_does_not_revoke_other_device(auth_api):
    client, engine, application = auth_api
    register(client)
    first = login(client).json()
    with TestClient(application) as other:
        second = login(other).json()
        assert post(client, "logout", csrf=first["csrf_token"]).status_code == 204
        assert me(other, second["access_token"]).status_code == 200
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.revoked_at.is_(None))
            )
            == 1
        )


def test_csrf_from_other_session_cannot_revoke_or_refresh(auth_api):
    client, engine, application = auth_api
    register(client)
    first = login(client).json()
    with TestClient(application) as other:
        second = login(other).json()
        other.cookies.clear()
        other.cookies.set("boso-dev-refresh", client.cookies.get("boso-dev-refresh"))
        other.cookies.set("boso-dev-csrf", second["csrf_token"])
        assert post(other, "refresh", csrf=second["csrf_token"]).status_code == 403
        assert post(other, "logout", csrf=second["csrf_token"]).status_code == 403
    assert me(client, first["access_token"]).status_code == 200
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.revoked_at.is_not(None))
            )
            == 0
        )


def test_unknown_refresh_does_not_revoke_any_session(auth_api):
    client, engine, _ = auth_api
    register(client)
    body = login(client).json()
    client.cookies.set(
        "boso-dev-refresh", security.new_refresh_token(), domain="testserver.local", path="/"
    )
    assert post(client, "refresh", csrf=body["csrf_token"]).status_code == 401
    assert me(client, body["access_token"]).status_code == 200
    with Session(engine) as db:
        assert db.scalar(select(AuthSession.revoked_at)) is None


@pytest.mark.parametrize("state", ["expired_session", "expired_token", "revoked", "inactive"])
def test_refresh_denies_invalid_session_without_issuing_tokens(auth_api, state):
    client, engine, _ = auth_api
    register(client)
    body = login(client).json()
    with Session(engine) as db:
        session = db.scalar(select(AuthSession))
        if state == "expired_session":
            session.created_at = security.now_utc() - timedelta(days=8)
            session.expires_at = security.now_utc() - timedelta(seconds=1)
        elif state == "expired_token":
            token = db.scalar(select(RefreshToken))
            token.created_at = security.now_utc() - timedelta(days=8)
            token.expires_at = security.now_utc() - timedelta(seconds=1)
        elif state == "revoked":
            session.revoked_at = security.now_utc()
            session.revocation_reason = "logout"
        else:
            db.scalar(select(User)).is_active = False
        db.commit()
    response = post(client, "refresh", csrf=body["csrf_token"])
    assert response.status_code == 401
    assert "access_token" not in response.json()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(RefreshToken)) == 1


def test_logout_is_idempotent_and_expired_cookie_is_current_session_only(auth_api):
    client, engine, _ = auth_api
    register(client)
    body = login(client).json()
    with Session(engine) as db:
        session = db.scalar(select(AuthSession))
        session.created_at = security.now_utc() - timedelta(days=8)
        session.expires_at = security.now_utc() - timedelta(seconds=1)
        db.commit()
    assert post(client, "logout", csrf=body["csrf_token"]).status_code == 204
    assert post(client, "logout").status_code == 204


def test_reuse_does_not_revoke_other_session(auth_api):
    client, engine, application = auth_api
    register(client)
    first = login(client).json()
    raw = client.cookies.get("boso-dev-refresh")
    with TestClient(application) as other:
        second = login(other).json()
        assert post(client, "refresh", csrf=first["csrf_token"]).status_code == 200
        client.cookies.set("boso-dev-refresh", raw, domain="testserver.local", path="/")
        assert post(client, "refresh", csrf=first["csrf_token"]).status_code == 401
        assert me(other, second["access_token"]).status_code == 200
        assert post(other, "refresh", csrf=second["csrf_token"]).status_code == 200
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.revoked_at.is_(None))
            )
            == 1
        )


def test_api_rate_limit_runs_before_password_hashing(auth_api):
    client, _, _ = auth_api
    limiter = client.app.state.auth_rate_limiter
    for _ in range(30):
        limiter.check("testclient", "/api/v1/auth/signup")
    response = register(client)
    assert response.status_code == 429
    assert response.json()["code"] == "AUTH_RATE_LIMITED"


def test_openapi_declares_bearer_credentials_and_no_refresh_body(auth_api):
    client, _, _ = auth_api
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "requestBody" not in schema["paths"]["/api/v1/auth/refresh"]["post"]
    assert set(schema["components"]["schemas"]["Credentials"]["properties"]) == {
        "email",
        "password",
    }


@pytest.mark.parametrize("state", ["expired", "revoked", "inactive", "wrong_owner"])
def test_access_checks_current_database_state_and_ownership(auth_api, state):
    client, engine, _ = auth_api
    register(client)
    body = login(client).json()
    with Session(engine) as db:
        session = db.scalar(select(AuthSession))
        if state == "expired":
            session.created_at = security.now_utc() - timedelta(days=8)
            session.expires_at = security.now_utc() - timedelta(days=1)
        elif state == "revoked":
            session.revoked_at = security.now_utc()
            session.revocation_reason = "logout"
        elif state == "inactive":
            db.scalar(select(User)).is_active = False
        else:
            other = User(email="other@example.com", password_hash="test-hash")
            db.add(other)
            db.flush()
            session.user_id = other.id
        db.commit()
    assert me(client, body["access_token"]).status_code == 401


def test_forged_jwt_owner_and_missing_auth_are_rejected(auth_api):
    client, _, _ = auth_api
    assert client.get("/api/v1/auth/me").status_code == 401
    register(client)
    token = login(client).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["sub"] = "00000000-0000-0000-0000-000000000001"
    # Even a correctly signed token with a mismatched session owner is denied.
    forged = jwt.encode(claims, get_settings().auth_jwt_key.get_secret_value(), algorithm="HS256")
    assert me(client, forged).status_code == 401
    owner = client.get("/test-owner/someone-else", headers={"Authorization": f"Bearer {token}"})
    assert owner.json()["authenticated_id"] == claims_from_token(token)["sub"]


def claims_from_token(token):
    return jwt.decode(token, options={"verify_signature": False})


def test_auth_validation_errors_and_logs_do_not_echo_secrets(auth_api, caplog):
    client, _, _ = auth_api
    response = post(client, "signup", {"email": "bad-email", "password": "short-secret"})
    assert response.status_code == 422
    assert "short-secret" not in response.text
    register(client)
    logged = login(client)
    token = logged.json()["access_token"]
    raw = client.cookies.get("boso-dev-refresh")
    assert PASSWORD not in caplog.text and token not in caplog.text and raw not in caplog.text
    assert logged.headers["Cache-Control"] == "no-store"


def test_cors_credentials_and_csrf_preflight(auth_api):
    client, _, _ = auth_api
    allowed = client.options(
        "/api/v1/auth/refresh",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Token,Content-Type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    denied = client.options(
        "/api/v1/auth/refresh",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize("path", ["login", "refresh", "logout", "signup"])
def test_commit_failure_does_not_send_tokens_or_success(auth_api, monkeypatch, path):
    client, engine, _ = auth_api
    register(client)
    logged = login(client).json()

    class FailedCommit(Session):
        def commit(self):
            raise OperationalError("commit", {}, Exception("test-only-driver-secret"))

    with patch(
        "app.core.db.sessionmaker", lambda *a, **kw: sessionmaker(*a, class_=FailedCommit, **kw)
    ):
        response = post(
            client,
            path,
            {"email": "second@example.com" if path == "signup" else EMAIL, "password": PASSWORD},
            csrf=logged["csrf_token"],
        )
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    assert "test-only-driver-secret" not in response.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1
        assert db.scalar(select(func.count()).select_from(RefreshToken)) == 1
        assert db.scalar(select(AuthSession.revoked_at)) is None


def test_auth_not_configured_fails_closed_without_connecting(auth_api, monkeypatch):
    client, _, _ = auth_api
    from app.core.config import Settings

    unconfigured = Settings(_env_file=None, auth_jwt_key=None, auth_csrf_key=None)
    monkeypatch.setattr("app.modules.auth.dependencies.get_settings", lambda: unconfigured)
    response = login(client)
    assert response.status_code == 503


def test_production_cookies_are_host_only_secure_and_refresh_httponly(auth_api, monkeypatch):
    _, engine, _ = auth_api
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("CORS_ORIGINS", '["https://web.example"]')
    get_settings.cache_clear()
    application = build_client(engine, monkeypatch)
    with TestClient(application, base_url="https://api.example") as client:
        headers = {"Origin": "https://web.example", "Content-Type": "application/json"}
        client.post(
            "/api/v1/auth/signup", json={"email": EMAIL, "password": PASSWORD}, headers=headers
        )
        response = client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=headers
        )
        assert response.status_code == 200
        values = response.headers.get_list("set-cookie")
        refresh = next(v for v in values if v.startswith("__Host-boso-refresh="))
        csrf = next(v for v in values if v.startswith("__Host-boso-csrf="))
        assert "HttpOnly" in refresh and "HttpOnly" not in csrf
        for value in (refresh, csrf):
            assert "Secure" in value and "SameSite=lax" in value and "Path=/" in value
            assert "Domain=" not in value and "Max-Age=" in value
