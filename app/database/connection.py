"""Async SQLAlchemy database connection and session factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database.models import Base
from app.services.waiters import waiters

_log = logging.getLogger(__name__)
_settings = get_settings()

# Resolve the database URL — fall back to SQLite if asyncpg is missing.
# Railway's build cache occasionally serves a stale image without asyncpg;
# this keeps the app running so all non-DB routes (kundli, panchang, chat)
# continue working until the cache is cleared and the image is rebuilt.
_db_url = _settings.database_url

if "postgresql" in _db_url or "asyncpg" in _db_url:
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        _log.warning(
            "asyncpg not installed — falling back to SQLite. "
            "Fix: clear Railway build cache or set DATABASE_URL=sqlite+aiosqlite:///./data/astrobro.db"
        )
        _db_url = "sqlite+aiosqlite:///./data/astrobro.db"

# SQLite is only used for development and tests: a fresh connection per use avoids sharing one across event loops.
_pool_args = {"poolclass": NullPool} if "sqlite" in _db_url else {}

engine = create_async_engine(
    _db_url,
    echo=_settings.debug,
    connect_args={"check_same_thread": False} if "sqlite" in _db_url else {},
    **_pool_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables. Call at startup."""
    if "sqlite" in _db_url and ":memory:" not in _db_url:
        # A fresh checkout has no data/ folder, and SQLite will not create it.
        Path(_db_url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            waiters.flush(session)
        except Exception:
            await session.rollback()
            waiters.discard(session)
            raise


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """A short transaction for code that is not a request dependency (a streaming reply, a background task).

    Commits on success, rolls back on error, and always releases the connection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            waiters.flush(session)
        except Exception:
            await session.rollback()
            waiters.discard(session)
            raise
