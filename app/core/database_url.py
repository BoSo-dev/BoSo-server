from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(ValueError):
    """Configuration failure whose message never contains the submitted URI."""


def is_supabase(url: URL) -> bool:
    host = (url.host or "").lower()
    return host.endswith((".supabase.co", ".supabase.com"))


def is_local(url: URL) -> bool:
    return (url.host or "").lower() in {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def resolve_database_url(value: str | URL, *, migration: bool = False) -> URL:
    try:
        url = make_url(value)
        port = url.port
    except (ArgumentError, ValueError, TypeError):
        raise DatabaseConfigurationError(
            "Invalid database URI; check its format and URL-encoded password"
        ) from None

    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername in {"sqlite", "sqlite+pysqlite"}:
        return url
    if url.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError("Use PostgreSQL with psycopg, or SQLite for local tests")
    # SQLAlchemy lets query options override the authority used by our checks.
    # Reject overrides rather than validate a different endpoint from the driver.
    if any(key.lower() in {"host", "hostaddr", "port"} for key in url.query):
        raise DatabaseConfigurationError(
            "Set database host and port in the URI authority; query overrides are not supported"
        )
    if not url.host or not url.database or "@" in url.host:
        raise DatabaseConfigurationError(
            "Database URI requires a host and database; URL-encode password characters"
        )

    sslmode = url.query.get("sslmode")
    if sslmode is not None and sslmode not in {
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise DatabaseConfigurationError("Invalid or repeated sslmode setting")
    if not is_local(url):
        if sslmode in {"disable", "allow", "prefer"}:
            raise DatabaseConfigurationError(
                "Remote PostgreSQL requires sslmode=require, verify-ca, or verify-full"
            )
        if sslmode is None:
            url = url.update_query_dict({"sslmode": "require"})
    if migration and is_supabase(url) and port == 6543:
        raise DatabaseConfigurationError(
            "Use a Direct or Session pooler URI for migrations via MIGRATION_DATABASE_URL"
        )
    return url
