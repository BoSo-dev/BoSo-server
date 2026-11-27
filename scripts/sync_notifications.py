"""Explicit, idempotent notification job. Dry run does not connect to a DB."""

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import make_engine
from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.notifications.service import synchronize


def run_job(engine):
    processed, created, last = 0, 0, None
    while True:
        with Session(engine) as db:
            statement = select(User.id).where(User.is_active.is_(True)).order_by(User.id).limit(100)
            if last is not None:
                statement = statement.where(User.id > last)
            owners = db.scalars(statement).all()
        if not owners:
            break
        for owner in owners:
            try:
                with Session(engine) as db, db.begin():
                    result = synchronize(db, owner)
                processed += 1
                created += result.created
            except AppError as exc:
                if exc.code != "USER_NOT_FOUND":
                    raise
        last = owners[-1]
    return {"processed": processed, "created": created}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps({"status": "dry_run", "database": "not_connected"}))
        return 0
    engine = None
    try:
        settings = get_settings()
        engine = make_engine(settings.get_database_url(), null_pool=True)
        result = run_job(engine)
        print(json.dumps({"status": "ok", **result}))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "code": "NOTIFICATION_JOB_FAILED"}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
