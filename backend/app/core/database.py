from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

_engine = None
_async_session_factory = None


def _get_engine():
    global _engine, _async_session_factory
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        _async_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def _get_session_factory():
    _get_engine()  # ensure engine is created
    return _async_session_factory


class Base(DeclarativeBase):
    pass


async def get_db():
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Bring the schema up to Alembic head at startup.

    The pgvector extension is enabled first (non-fatal if the instance does
    not support it — migrations that need it will fail loudly instead).
    """
    import asyncio
    import logging

    from sqlalchemy import text

    from app.core.migrations import run_migrations

    logger = logging.getLogger(__name__)
    engine = _get_engine()
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as e:  # noqa: BLE001 — hosted PG without pgvector should still boot
            logger.warning("Could not enable pgvector extension: %s", e)

    await asyncio.to_thread(run_migrations)
