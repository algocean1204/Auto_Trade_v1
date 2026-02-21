"""
Database connection module.
Provides async SQLAlchemy engine, session factory, and Redis client.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis_client: aioredis.Redis | None = None


def _build_database_url() -> str:
    user = os.getenv("DB_USER", "trading")
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError(
            "DB_PASSWORD 환경변수가 설정되지 않았습니다. "
            ".env 파일에 DB_PASSWORD를 반드시 설정하세요."
        )
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "trading_system")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


def get_engine() -> AsyncEngine:
    """Return the singleton async engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _build_database_url(),
            echo=os.getenv("DB_ECHO", "false").lower() == "true",
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with automatic commit/rollback."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_redis() -> aioredis.Redis:
    """Return the singleton async Redis client."""
    global _redis_client
    if _redis_client is None:
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD", None)
        _redis_client = aioredis.Redis(
            host=host,
            port=port,
            password=password if password else None,
            decode_responses=True,
        )
    return _redis_client


async def init_db() -> None:
    """Verify database connectivity at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """Dispose engine and close Redis on shutdown."""
    global _engine, _session_factory, _redis_client
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
