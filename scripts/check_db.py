"""Read-only PostgreSQL diagnostics with credential-safe output."""

import argparse
import json
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database_checks import inspect_database, safe_database_error
from app.core.database_url import is_local
from app.core.db import make_engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migration",
        action="store_true",
        help="Check the migration connection and schema CREATE permission",
    )
    args = parser.parse_args()
    engine = None
    try:
        settings = get_settings()
        url = settings.get_database_url(migration=args.migration)
        engine = make_engine(url, connect_timeout=settings.db_connect_timeout, null_pool=True)
        report = inspect_database(engine)
        checks = report["permissions"]
        passed = checks["can_connect"] and checks["schema_usage"]
        if not is_local(url):
            passed = passed and report["client_tls"]
        if args.migration:
            passed = passed and checks["schema_create"]
        report["status"] = "ok" if passed else "failed"
        print(json.dumps(report))
        return 0 if passed else 1
    except SQLAlchemyError as exc:
        # Never print exception text, which can include host/user/password/SQL.
        print(json.dumps({"status": "failed", "code": safe_database_error(exc)}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "DATABASE_CONFIGURATION_OR_CHECK_FAILED"}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
