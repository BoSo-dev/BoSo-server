"""Validate reviewed policy files; write only when --apply is explicit."""

import argparse
import json
import os
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database_url import is_local
from app.core.db import make_engine
from app.modules.policies.schemas import PolicyImportFile
from app.modules.policies.service import PolicyImportError, import_policies, validate_reviews

MAX_FILE_BYTES = 1024 * 1024


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyImportError("POLICY_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def load_file(path: Path):
    # Bound the read itself, not only stat(), to cover changing/oversized files.
    with path.open("rb") as source:
        payload = source.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise PolicyImportError("POLICY_FILE_TOO_LARGE")
    data = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique_keys)
    batch = PolicyImportFile.model_validate(data)
    validate_reviews(batch)
    return batch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Write the entire file in one transaction"
    )
    args = parser.parse_args(argv)
    engine = None
    try:
        batch = load_file(args.file)
        if not args.apply:
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "policies": len(batch.policies),
                        "database": "not_connected",
                    }
                )
            )
            return 0
        settings = get_settings()
        url = settings.get_database_url()
        if any(item.is_example for item in batch.policies):
            local_target = url.get_backend_name() == "sqlite" or (
                is_local(url)
                and not set(url.query) - {"sslmode"}
                and not any(
                    os.getenv(name) for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")
                )
            )
            if settings.app_env == "production" or not local_target:
                raise PolicyImportError("POLICY_EXAMPLE_TARGET_FORBIDDEN")
        engine = make_engine(url, null_pool=True)
        with Session(engine) as db, db.begin():
            counts = import_policies(db, batch)
        # A success is printed only after the transaction committed.
        print(json.dumps({"status": "ok", **counts}))
        return 0
    except PolicyImportError as exc:
        print(json.dumps({"status": "failed", "code": str(exc)}))
    except (ValidationError, ValueError, UnicodeError, OSError):
        print(json.dumps({"status": "failed", "code": "POLICY_FILE_INVALID"}))
    except Exception:
        # No driver exception, SQL, file contents, path or connection URI is echoed.
        print(json.dumps({"status": "failed", "code": "POLICY_IMPORT_FAILED"}))
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
