"""Engines and sessions for the app's own database, with migrations applied on first use."""

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from core.settings import DatabaseType, settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_lock = threading.Lock()
_engines: dict[str, Engine] = {}
_async_engines: dict[str, AsyncEngine] = {}
_migrated: set[str] = set()


def database_url() -> str:
    if settings.APP_DATABASE_URL:
        return settings.APP_DATABASE_URL
    if settings.DATABASE_TYPE == DatabaseType.POSTGRES:
        password = (
            settings.POSTGRES_PASSWORD.get_secret_value() if settings.POSTGRES_PASSWORD else ""
        )
        return (
            f"postgresql+psycopg://{quote(settings.POSTGRES_USER or '', safe='')}:{quote(password, safe='')}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
    return "sqlite:///app.db"


def _async_url(url: str) -> str:
    if url.startswith("sqlite:"):
        return url.replace("sqlite:", "sqlite+aiosqlite:", 1)
    if url.startswith("postgresql:"):
        return url.replace("postgresql:", "postgresql+psycopg:", 1)
    return url


def _tune_sqlite(engine: Engine) -> None:
    # The service (async) and ingestion (sync, worker thread) share the file.
    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # pragma: no cover - driver callback
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _migrate(engine: Engine, url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    _migrated.add(url)


def get_engine() -> Engine:
    url = database_url()
    with _lock:
        if url not in _engines:
            if url.startswith("sqlite"):
                # A file database: connecting is cheap, and nothing stays open between uses.
                engine = create_engine(url, poolclass=NullPool)
                _tune_sqlite(engine)
            else:
                engine = create_engine(url, pool_pre_ping=True)
            _engines[url] = engine
        engine = _engines[url]
        if url not in _migrated:
            _migrate(engine, url)
    return engine


def get_async_engine() -> AsyncEngine:
    get_engine()
    url = database_url()
    with _lock:
        if url not in _async_engines:
            if url.startswith("sqlite"):
                engine = create_async_engine(_async_url(url), poolclass=NullPool)
                _tune_sqlite(engine.sync_engine)
            else:
                engine = create_async_engine(_async_url(url), pool_pre_ping=True)
            _async_engines[url] = engine
        return _async_engines[url]


@contextmanager
def session_scope() -> Iterator[Session]:
    """A sync session that commits on success; used by ingestion, which runs in worker threads."""
    with sessionmaker(get_engine(), expire_on_commit=False).begin() as session:
        yield session


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """An async session that commits on success; used by the FastAPI service."""
    factory = async_sessionmaker(get_async_engine(), expire_on_commit=False)
    async with factory.begin() as session:
        yield session


async def dispose_engines() -> None:
    with _lock:
        async_engines = list(_async_engines.values())
        engines = list(_engines.values())
        _async_engines.clear()
        _engines.clear()
        _migrated.clear()
    for async_engine in async_engines:
        await async_engine.dispose()
    for engine in engines:
        engine.dispose()
