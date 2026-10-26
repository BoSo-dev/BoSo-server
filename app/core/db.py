from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database_url import resolve_database_url


class Base(DeclarativeBase):
    pass


def make_engine(
    url: str | URL,
    *,
    pool_size: int = 5,
    max_overflow: int = 0,
    connect_timeout: int = 5,
    pool_timeout: int = 10,
    null_pool: bool = False,
):
    url = resolve_database_url(url)
    sqlite = url.get_backend_name() == "sqlite"
    options = (
        {"check_same_thread": False}
        if sqlite
        else {
            "connect_timeout": connect_timeout,
            # Works with Direct/Session connections and transaction poolers alike.
            "prepare_threshold": None,
        }
    )
    pool = (
        {}
        if sqlite
        else {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
        }
    )
    if null_pool:
        pool = {"poolclass": NullPool}
    engine = create_engine(
        url, pool_pre_ping=True, connect_args=options, hide_parameters=True, **pool
    )
    if sqlite:

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache
def get_engine():
    settings = get_settings()
    return make_engine(
        settings.get_database_url(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_timeout=settings.db_connect_timeout,
        pool_timeout=settings.db_pool_timeout,
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
