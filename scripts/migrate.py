"""Run Alembic upgrades without leaking connection details on failure."""

import json

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError

from alembic import command
from app.core.database_checks import safe_database_error


def main() -> int:
    try:
        config = Config("alembic.ini")
        heads = ScriptDirectory.from_config(config).get_heads()
        command.upgrade(config, "head")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "revision_count": len(heads),
                    "note": "no_domain_revisions" if not heads else "upgraded_to_head",
                }
            )
        )
        return 0
    except SQLAlchemyError as exc:
        print(json.dumps({"status": "failed", "code": safe_database_error(exc)}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "DATABASE_MIGRATION_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
