from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str, *, pool_size: int = 5, max_overflow: int = 0):
    options = {"check_same_thread": False} if url.startswith("sqlite") else {"connect_timeout": 5}
    pool = (
        {}
        if url.startswith("sqlite")
        else {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": 10,
        }
    )
    engine = create_engine(url, pool_pre_ping=True, connect_args=options, **pool)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache
def get_engine():
    settings = get_settings()
    return make_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def get_db():
    factory = sessionmaker(get_engine(), expire_on_commit=False)
    with factory() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
