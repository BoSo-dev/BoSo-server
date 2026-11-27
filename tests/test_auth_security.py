from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.auth import cookies, security
from app.modules.auth.dependencies import AuthRateLimiter
from app.modules.auth.schemas import Credentials

# Public, test-only keys. Never use these outside isolated tests.
JWT_TEST_KEY = "test-only-jwt-key-" + "a" * 64
CSRF_TEST_KEY = "test-only-csrf-key-" + "b" * 40


@pytest.fixture
def auth_settings():
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///unused-auth-test.db",
        migration_database_url=None,
        auth_jwt_key=JWT_TEST_KEY,
        auth_csrf_key=CSRF_TEST_KEY,
    )


def test_password_hash_is_salted_argon2id_and_verifies():
    password = "test-only-long-password"
    first = security.password_hasher.hash(password)
    second = security.password_hasher.hash(password)
    assert first.startswith("$argon2id$")
    assert first != second
    assert password not in first
    assert security.verify_password(first, password)
    assert not security.verify_password(first, password + "wrong")
    assert not security.verify_password("invalid-hash", password)


def test_access_lifetime_is_capped_by_session(auth_settings):
    user_id, session_id = uuid4(), uuid4()
    for remaining, expected in [(timedelta(days=7), 900), (timedelta(seconds=50), 50)]:
        token, lifetime = security.issue_access(
            auth_settings, user_id, session_id, datetime.now(UTC) + remaining
        )
        assert security.decode_access(auth_settings, token) == (user_id, session_id)
        assert expected - 1 <= lifetime <= expected


def claims(auth_settings):
    now = int(datetime.now(UTC).timestamp())
    return {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "iat": now,
        "exp": now + 900,
        "iss": auth_settings.auth_jwt_issuer,
        "aud": auth_settings.auth_jwt_audience,
        "type": "access",
    }


@pytest.mark.parametrize("missing", ["sub", "sid", "iat", "exp", "iss", "aud", "type"])
def test_access_rejects_missing_required_claim(auth_settings, missing):
    payload = claims(auth_settings)
    payload.pop(missing)
    token = jwt.encode(payload, JWT_TEST_KEY, algorithm="HS256")
    with pytest.raises(AppError) as error:
        security.decode_access(auth_settings, token)
    assert error.value.status == 401


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "other-issuer"},
        {"aud": "other-audience"},
        {"aud": ["boso-web", "other-audience"]},
        {"type": "refresh"},
        {"sub": "not-a-uuid"},
        {"sid": 123},
        {"exp": 1},
        {"exp": int(datetime.now(UTC).timestamp()) + 3600},
        {"iat": int(datetime.now(UTC).timestamp()) + 100},
        {"iat": "123"},
        {"exp": True},
    ],
)
def test_access_rejects_invalid_claims(auth_settings, override):
    token = jwt.encode({**claims(auth_settings), **override}, JWT_TEST_KEY, algorithm="HS256")
    with pytest.raises(AppError):
        security.decode_access(auth_settings, token)


@pytest.mark.parametrize("algorithm", ["HS384", "HS512", "none"])
def test_access_rejects_other_algorithms(auth_settings, algorithm):
    token = jwt.encode(
        claims(auth_settings), JWT_TEST_KEY if algorithm != "none" else None, algorithm=algorithm
    )
    with pytest.raises(AppError):
        security.decode_access(auth_settings, token)


def test_access_rejects_signature_tampering(auth_settings):
    token = jwt.encode(claims(auth_settings), JWT_TEST_KEY + "other", algorithm="HS256")
    with pytest.raises(AppError):
        security.decode_access(auth_settings, token)


def test_refresh_randomness_format_and_hash():
    tokens = {security.new_refresh_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(security.valid_refresh_format(token) for token in tokens)
    assert all(len(security.refresh_hash(token)) == 64 for token in tokens)
    assert not security.valid_refresh_format("x" * 10000)


def test_signed_csrf_is_bound_to_session_and_cookie(auth_settings):
    session_id = uuid4()
    csrf = security.new_csrf(auth_settings, session_id)
    security.verify_csrf(auth_settings, session_id, csrf, csrf)
    for sid, cookie, header in [
        (uuid4(), csrf, csrf),
        (session_id, csrf, None),
        (session_id, None, csrf),
        (session_id, csrf, csrf + "a"),
        (session_id, "x" * 43 + "." + "0" * 64, "x" * 43 + "." + "0" * 64),
        (session_id, "한글", "한글"),
        (session_id, csrf, "한글"),
    ]:
        with pytest.raises(AppError) as error:
            security.verify_csrf(auth_settings, sid, cookie, header)
        assert error.value.status == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_jwt_key": "short"},
        {"auth_csrf_key": "short"},
        {"auth_jwt_key": JWT_TEST_KEY, "auth_csrf_key": JWT_TEST_KEY},
        {"cors_origins": ["*"]},
        {"cors_origins": ["https://web.example/path"]},
        {"cors_origins": ["https://user:pass@web.example"]},
        {"auth_jwt_issuer": ""},
        {"auth_jwt_audience": ""},
    ],
)
def test_auth_configuration_rejects_unsafe_values(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_production_requires_separate_keys_and_https():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", cors_origins=["https://web.example"])
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_jwt_key=JWT_TEST_KEY,
        auth_csrf_key=CSRF_TEST_KEY,
        cors_origins=["https://web.example"],
    )
    assert cookies.cookie_names(settings) == ("__Host-boso-refresh", "__Host-boso-csrf")
    output = str(settings) + repr(settings) + settings.model_dump_json()
    assert JWT_TEST_KEY not in output and CSRF_TEST_KEY not in output


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_credentials_enforce_password_bounds_without_repr_leak(password):
    with pytest.raises(ValidationError):
        Credentials(email="member@example.com", password=password)
    body = Credentials(email=" MEMBER@EXAMPLE.COM ", password="a-long-test-password")
    assert body.email == "member@example.com"
    assert "a-long-test-password" not in repr(body)


def test_rate_limiter_bounds_state_and_expires(monkeypatch):
    limiter = AuthRateLimiter()
    clock = [1.0]
    monkeypatch.setattr("app.modules.auth.dependencies.monotonic", lambda: clock[0])
    for _ in range(30):
        limiter.check("peer", "/auth/login")
    with pytest.raises(AppError) as error:
        limiter.check("peer", "/auth/login")
    assert error.value.status == 429
    clock[0] += 60
    limiter.check("peer", "/auth/login")
    for i in range(4100):
        limiter.check(str(i), "/auth/login")
    assert len(limiter.entries) == 4096
