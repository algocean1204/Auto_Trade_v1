"""
DatabaseGateway (C0.2) -- PostgreSQL 비동기 세션 팩토리를 생성하고 제공한다.

asyncpg 드라이버 기반 SQLAlchemy 2.0 비동기 엔진을 관리한다.
싱글톤 SessionFactory를 통해 프로젝트 전체에서 동일한 커넥션 풀을 공유한다.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from src.common.logger import get_logger

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = get_logger(__name__)

# -- 싱글톤 인스턴스 --
_instance: SessionFactory | None = None


class Base(DeclarativeBase):
    """모든 ORM 모델의 기본 클래스이다.

    실제 테이블 모델은 각 Feature 폴더에서 이 Base를 import하여 정의한다.
    """

    pass


class SessionFactory:
    """DB 세션 팩토리 -- async with get_session() as session 패턴이다.

    SQLAlchemy 2.0 비동기 엔진과 세션 메이커를 내부에 보유하며,
    get_session() 컨텍스트 매니저로 자동 커밋/롤백을 관리한다.
    """

    def __init__(self, database_url: str) -> None:
        """엔진과 세션 메이커를 초기화한다.

        Args:
            database_url: PostgreSQL 접속 URL (asyncpg 드라이버 포함)
        """
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("DatabaseGateway 엔진 생성 완료 (pool_size=10, max_overflow=20)")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """비동기 DB 세션을 제공한다. 정상 종료 시 커밋, 예외 시 롤백한다."""
        session = self._session_maker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        """엔진과 커넥션 풀을 정리한다. 애플리케이션 종료 시 호출해야 한다."""
        await self._engine.dispose()
        logger.info("DatabaseGateway 엔진 종료 완료")


def get_session_factory(database_url: str | None = None) -> SessionFactory:
    """SessionFactory 싱글톤을 반환한다.

    최초 호출 시 database_url이 필수이다. 이후에는 캐싱된 인스턴스를 반환한다.

    Args:
        database_url: PostgreSQL 접속 URL. 최초 호출 시 필수.

    Returns:
        SessionFactory 싱글톤 인스턴스
    """
    global _instance
    if _instance is not None:
        return _instance

    if database_url is None:
        raise ValueError(
            "최초 호출 시 database_url이 필수이다. "
            "SecretVault에서 DATABASE_URL을 조회하여 전달해야 한다."
        )

    _instance = SessionFactory(database_url)
    return _instance


def reset_session_factory() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
