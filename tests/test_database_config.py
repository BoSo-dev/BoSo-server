from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg

from app.core.config import Settings
from app.core.database_url import DatabaseConfigurationError, resolve_database_url
from app.core.db import make_engine

LOCAL_URL = "postgresql+psycopg://test_user:test_password@localhost:5432/test_db"
REMOTE_URL = "postgresql://test_user:test_password@db.example.invalid:5432/test_db"
SESSION_URL = "postgresql://postgres.test:test_password@test.pooler.supabase.com:5432/postgres"
TRANSACTION_URL = SESSION_URL.replace(":5432/", ":6543/")


@pytest.fixture
def settings_factory():
    def create(**overrides):
        return Settings(
            _env_file=None,
            **{
                "app_env": "test",
                "database_url": LOCAL_URL,
                "migration_database_url": None,
                "cors_origins": [],
                **overrides,
            },
        )

    return create


@pytest.mark.parametrize("driver", ["postgres", "postgresql", "postgresql+psycopg"])
def test_database_url_normalizes_driver_and_preserves_encoded_password(driver):
    url = resolve_database_url(
        f"{driver}://test_user:p%40%3A%2F%25%23@db.example.invalid:5432/test_db"
        "?application_name=boso-test"
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "test_user"
    assert url.password == "p@:/%#"
    assert url.host == "db.example.invalid"
    assert url.port == 5432
    assert url.database == "test_db"
    assert url.query == {"application_name": "boso-test", "sslmode": "require"}
    assert resolve_database_url(url) == url


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_remote_database_preserves_explicit_ssl_and_certificate_options(mode):
    url = resolve_database_url(f"{REMOTE_URL}?sslmode={mode}&sslrootcert=test-ca.crt")
    assert url.query == {"sslmode": mode, "sslrootcert": "test-ca.crt"}


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=disable",
        "sslmode=allow",
        "sslmode=prefer",
        "sslmode=invalid",
        "sslmode=require&sslmode=disable",
    ],
)
def test_remote_database_rejects_weak_invalid_or_duplicate_ssl(query):
    with pytest.raises(DatabaseConfigurationError):
        resolve_database_url(f"{REMOTE_URL}?{query}")


def test_local_database_does_not_require_ssl():
    assert "sslmode" not in resolve_database_url(LOCAL_URL).query
    assert resolve_database_url(f"{LOCAL_URL}?sslmode=disable").query["sslmode"] == "disable"


@pytest.mark.parametrize(
    "query",
    [
        "host=db.example.invalid",
        "hostaddr=203.0.113.10",
        "port=6543",
        "host=db.example.invalid&host=other.example.invalid",
        "ho%73t=db.example.invalid",
        "Host=db.example.invalid",
        "HOSTADDR=203.0.113.10",
        "Port=6543",
    ],
)
@pytest.mark.parametrize("migration", [False, True])
def test_query_endpoint_overrides_cannot_bypass_local_ssl_check(query, migration):
    with pytest.raises(DatabaseConfigurationError, match="query overrides") as error:
        resolve_database_url(f"{LOCAL_URL}?{query}&sslmode=disable", migration=migration)
    assert "test_password" not in str(error.value)
    assert "db.example.invalid" not in str(error.value)


def test_query_port_override_cannot_bypass_transaction_pooler_migration_check():
    with pytest.raises(DatabaseConfigurationError, match="query overrides"):
        resolve_database_url(f"{SESSION_URL}?port=6543", migration=True)


@pytest.mark.parametrize("query", ["host=db.example.invalid", "hostaddr=203.0.113.10", "port=6543"])
def test_engine_rejects_endpoint_override_before_engine_creation(query, monkeypatch):
    create_engine = Mock()
    monkeypatch.setattr("app.core.db.create_engine", create_engine)
    with pytest.raises(DatabaseConfigurationError, match="query overrides"):
        make_engine(f"{LOCAL_URL}?{query}&sslmode=disable")
    create_engine.assert_not_called()


@pytest.mark.parametrize("field", ["database_url", "migration_database_url"])
def test_settings_reject_endpoint_overrides(field, settings_factory):
    with pytest.raises(ValidationError, match="query overrides"):
        settings_factory(**{field: f"{LOCAL_URL}?host=db.example.invalid&sslmode=disable"})


def test_session_pooler_driver_target_matches_validated_url():
    url = resolve_database_url(f"{SESSION_URL}?application_name=boso-test", migration=True)
    # Build driver arguments only: never connect to the placeholder host.
    _, options = PGDialect_psycopg().create_connect_args(url)
    assert options["host"] == url.host
    assert options["port"] == url.port == 5432
    assert options["sslmode"] == "require"
    assert options["application_name"] == "boso-test"


def test_sqlite_test_database_is_preserved():
    assert str(resolve_database_url("sqlite:///test.db", migration=True)) == "sqlite:///test.db"


@pytest.mark.parametrize(
    "url",
    [
        "not-a-uri private-user private-password private-host private-db",
        "mysql://private-user:private-password@private-host/private-db",
        "postgresql://private-user:private-password@private-host:bad-port/private-db",
        "postgresql://private-user:private-password@private-host",
        "postgresql://private-user:private-password@unexpected@private-host/private-db",
    ],
)
def test_invalid_database_url_error_does_not_echo_connection_details(url):
    with pytest.raises(DatabaseConfigurationError) as error:
        resolve_database_url(url)
    for marker in (url, "private-user", "private-password", "private-host", "private-db"):
        assert marker not in str(error.value)


def test_migration_url_defaults_to_runtime_connection(settings_factory):
    settings = settings_factory(database_url=SESSION_URL)
    assert settings.get_database_url(migration=True) == settings.get_database_url()


def test_migration_url_can_be_separate_from_runtime_connection(settings_factory):
    settings = settings_factory(database_url=TRANSACTION_URL, migration_database_url=SESSION_URL)
    assert settings.get_database_url().port == 6543
    assert settings.get_database_url(migration=True).port == 5432
    assert settings.get_database_url(migration=True).query["sslmode"] == "require"


def test_transaction_pooler_is_rejected_for_migrations(settings_factory):
    settings = settings_factory(database_url=TRANSACTION_URL)
    with pytest.raises(DatabaseConfigurationError, match="Direct or Session"):
        settings.get_database_url(migration=True)
    with pytest.raises(ValidationError, match="Direct or Session"):
        settings_factory(migration_database_url=TRANSACTION_URL)


def test_database_urls_are_redacted_in_settings_output(settings_factory):
    settings = settings_factory(
        database_url=REMOTE_URL,
        migration_database_url=SESSION_URL,
    )
    output = repr(settings) + str(settings) + settings.model_dump_json()
    for marker in (REMOTE_URL, SESSION_URL, "test_user", "test_password", "db.example.invalid"):
        assert marker not in output


@pytest.mark.parametrize("field", ["database_url", "migration_database_url"])
def test_settings_validation_error_hides_submitted_connection(field, settings_factory):
    url = "mysql://private-user:private-password@private-host/private-db"
    with pytest.raises(ValidationError) as error:
        settings_factory(**{field: url})
    for marker in (url, "private-user", "private-password", "private-host", "private-db"):
        assert marker not in str(error.value)


def test_engine_uses_normalized_ssl_url_and_hides_sql_parameters(monkeypatch):
    create_engine = Mock()
    monkeypatch.setattr("app.core.db.create_engine", create_engine)
    assert make_engine(REMOTE_URL) is create_engine.return_value
    args, options = create_engine.call_args
    assert args[0].drivername == "postgresql+psycopg"
    assert args[0].query["sslmode"] == "require"
    assert options["hide_parameters"] is True
    assert options["connect_args"] == {"connect_timeout": 5, "prepare_threshold": None}
