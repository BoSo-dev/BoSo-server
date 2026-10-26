from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Engine


def safe_database_error(exc: Exception) -> str:
    """Classify failures without returning any driver-supplied message text."""
    original = getattr(exc, "orig", exc)
    state = getattr(original, "sqlstate", None)
    message = str(original).lower()
    if state in {"28P01", "28000"} or "password authentication failed" in message:
        return "DATABASE_AUTHENTICATION_FAILED"
    if "tenant or user not found" in message:
        return "DATABASE_POOLER_CONFIGURATION_FAILED"
    if any(
        term in message
        for term in (
            "getaddrinfo",
            "could not translate host",
            "failed to resolve",
            "name or service not known",
        )
    ):
        return "DATABASE_HOST_RESOLUTION_FAILED"
    if any(
        term in message
        for term in ("certificate verify failed", "ssl error", "sslmode", "does not support ssl")
    ):
        return "DATABASE_TLS_FAILED"
    if any(
        term in message
        for term in (
            "connection refused",
            "timeout expired",
            "connection timed out",
            "network is unreachable",
        )
    ):
        return "DATABASE_NETWORK_FAILED"
    if state == "42501":
        return "DATABASE_PERMISSION_DENIED"
    return (
        "DATABASE_QUERY_FAILED" if getattr(exc, "statement", None) else "DATABASE_CONNECTION_FAILED"
    )


def inspect_database(engine: Engine) -> dict:
    """Read-only connection/privilege checks, returning no connection identifiers."""
    if engine.dialect.name != "postgresql":
        raise ValueError("Database diagnostics require PostgreSQL")
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = 5000"))
        connection.execute(text("SELECT 1"))
        client_tls = bool(connection.connection.driver_connection.pgconn.ssl_in_use)
        backend_tls = connection.scalar(
            text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        )
        permissions = (
            connection.execute(
                text("""
            SELECT
              has_database_privilege(current_database(), 'CONNECT') AS can_connect,
              has_schema_privilege('public', 'USAGE') AS schema_usage,
              has_schema_privilege('public', 'CREATE') AS schema_create,
              EXISTS (SELECT 1 FROM pg_roles
                      WHERE rolname = current_user AND (rolsuper OR rolbypassrls))
                AS role_can_bypass_rls
        """)
            )
            .mappings()
            .one()
        )
        # Only boolean status is returned, never revision data from another project.
        revisions = MigrationContext.configure(connection).get_current_heads()
        return {
            "connection": "ok",
            "client_tls": client_tls,
            "backend_tls": backend_tls,
            "permissions": dict(permissions),
            "migration_history_present": bool(revisions),
        }
