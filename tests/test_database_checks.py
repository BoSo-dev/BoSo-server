import json
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.core.database_checks import safe_database_error
from app.core.database_url import resolve_database_url
from scripts import check_db, migrate

PRIVATE_DETAILS = "postgresql://private-user:private-password@private-host/private-db"


@pytest.mark.parametrize(
    ("state", "message", "expected"),
    [
        ("28P01", "rejected", "DATABASE_AUTHENTICATION_FAILED"),
        ("28000", "rejected", "DATABASE_AUTHENTICATION_FAILED"),
        (None, "password authentication failed", "DATABASE_AUTHENTICATION_FAILED"),
        (None, "Tenant or user not found", "DATABASE_POOLER_CONFIGURATION_FAILED"),
        (None, "getaddrinfo failed", "DATABASE_HOST_RESOLUTION_FAILED"),
        (None, "certificate verify failed", "DATABASE_TLS_FAILED"),
        (None, "connection timed out", "DATABASE_NETWORK_FAILED"),
        ("42501", "permission denied", "DATABASE_PERMISSION_DENIED"),
        (None, "unknown failure", "DATABASE_CONNECTION_FAILED"),
    ],
)
def test_database_errors_return_only_safe_codes(state, message, expected):
    original = Exception(f"{message} {PRIVATE_DETAILS}")
    original.sqlstate = state
    error = OperationalError(None, {}, original)
    assert safe_database_error(error) == expected


@pytest.fixture
def diagnostic_mocks(monkeypatch):
    settings = Mock()
    settings.get_database_url.return_value = resolve_database_url(
        "postgresql://test_user:test_password@db.example.invalid/test_db"
    )
    settings.db_connect_timeout = 5
    engine = Mock()
    report = {
        "connection": "ok",
        "client_tls": True,
        "backend_tls": False,
        "permissions": {
            "can_connect": True,
            "schema_usage": True,
            "schema_create": True,
            "role_can_bypass_rls": True,
        },
        "migration_history_present": False,
    }
    inspect_database = Mock(return_value=report)
    monkeypatch.setattr(check_db, "get_settings", lambda: settings)
    monkeypatch.setattr(check_db, "make_engine", Mock(return_value=engine))
    monkeypatch.setattr(check_db, "inspect_database", inspect_database)
    monkeypatch.setattr("sys.argv", ["check_db.py"])
    return settings, engine, inspect_database, report


def test_diagnostics_report_connection_not_complete_security_audit(diagnostic_mocks, capsys):
    settings, engine, inspect_database, _ = diagnostic_mocks
    assert check_db.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["backend_tls"] is False
    assert report["permissions"]["role_can_bypass_rls"] is True
    assert report["migration_history_present"] is False
    settings.get_database_url.assert_called_once_with(migration=False)
    inspect_database.assert_called_once_with(engine)
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("failed_check", ["client_tls", "can_connect", "schema_usage"])
def test_diagnostics_reject_missing_remote_tls_or_permissions(
    failed_check, diagnostic_mocks, capsys
):
    _, engine, _, report = diagnostic_mocks
    if failed_check == "client_tls":
        report["client_tls"] = False
    else:
        report["permissions"][failed_check] = False
    assert check_db.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    engine.dispose.assert_called_once()


def test_migration_diagnostics_require_schema_create(diagnostic_mocks, monkeypatch, capsys):
    settings, _, _, report = diagnostic_mocks
    report["permissions"]["schema_create"] = False
    monkeypatch.setattr("sys.argv", ["check_db.py", "--migration"])
    assert check_db.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    settings.get_database_url.assert_called_once_with(migration=True)


@pytest.mark.parametrize("failure_stage", ["configuration", "connection"])
def test_diagnostics_failure_output_excludes_connection_details(
    failure_stage, diagnostic_mocks, monkeypatch, capsys
):
    _, engine, inspect_database, _ = diagnostic_mocks
    if failure_stage == "configuration":
        monkeypatch.setattr(check_db, "get_settings", Mock(side_effect=ValueError(PRIVATE_DETAILS)))
        expected = "DATABASE_CONFIGURATION_OR_CHECK_FAILED"
    else:
        inspect_database.side_effect = OperationalError(
            "SELECT private-data", {"password": "private-password"}, Exception(PRIVATE_DETAILS)
        )
        expected = "DATABASE_QUERY_FAILED"
    assert check_db.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "failed", "code": expected}
    assert captured.err == ""
    if failure_stage == "connection":
        engine.dispose.assert_called_once()


@pytest.mark.parametrize("driver_error", [False, True])
def test_migration_failure_output_excludes_connection_details(driver_error, monkeypatch, capsys):
    # Mock both Alembic operations: never connect or apply migrations in this test.
    monkeypatch.setattr(migrate.ScriptDirectory, "from_config", Mock())
    error = (
        OperationalError(None, {}, Exception(PRIVATE_DETAILS))
        if driver_error
        else ValueError(PRIVATE_DETAILS)
    )
    upgrade = Mock(side_effect=error)
    monkeypatch.setattr(migrate.command, "upgrade", upgrade)
    assert migrate.main() == 1
    expected = "DATABASE_CONNECTION_FAILED" if driver_error else "DATABASE_MIGRATION_FAILED"
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "failed", "code": expected}
    assert captured.err == ""
    upgrade.assert_called_once()
