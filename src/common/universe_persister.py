"""UniversePersister -- 유니버스 설정을 DB에 영속화한다.

DB = source of truth. 부팅 시 DB가 비어있으면 하드코딩 _ETF_RAW 데이터로 시드한다.
API에서 add/toggle/delete 시 즉시 DB에 반영한다.
"""
from __future__ import annotations

from sqlalchemy import select, update, delete

from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger

logger = get_logger(__name__)

# DB 모델에서 사용할 필드 목록이다
_TICKER_FIELDS: list[str] = [
    "ticker", "name", "exchange", "sector", "leverage",
    "is_inverse", "pair_ticker", "enabled",
]


class UniversePersister:
    """유니버스 티커 설정을 PostgreSQL에 영속화한다.

    DB = source of truth. 부팅 시 DB가 비어있으면 하드코딩 데이터로 시드한다.
    """

    def __init__(self, db: SessionFactory) -> None:
        """DB 세션 팩토리를 주입받아 초기화한다."""
        self._db = db

    async def load_or_seed(self) -> list[dict]:
        """DB에서 유니버스를 로드한다. 비어있으면 기본 데이터로 시드한다.

        Returns:
            티커 메타 정보 딕셔너리 목록이다. 각 항목은 _TICKER_FIELDS 키를 포함한다.
        """
        from src.db.models import UniverseConfig

        try:
            async with self._db.get_session() as session:
                result = await session.execute(
                    select(UniverseConfig).order_by(UniverseConfig.id)
                )
                rows = result.scalars().all()

                if rows:
                    logger.info("DB에서 유니버스 로드 완료: %d개 티커", len(rows))
                    return [self._row_to_dict(r) for r in rows]

                # DB가 비어있으면 하드코딩 데이터로 시드한다
                logger.info("DB 유니버스가 비어있다. 하드코딩 데이터로 시드한다.")
                return await self._seed_from_hardcoded(session)

        except Exception:
            logger.exception("유니버스 로드/시드 실패 -- 빈 목록을 반환한다")
            return []

    async def _seed_from_hardcoded(self, session: object) -> list[dict]:
        """하드코딩 _ETF_RAW 데이터를 DB에 삽입하고 반환한다."""
        from src.common.ticker_registry import _ETF_FIELDS, _ETF_RAW
        from src.db.models import UniverseConfig

        seeded: list[dict] = []
        for row_tuple in _ETF_RAW:
            data = dict(zip(_ETF_FIELDS, row_tuple))
            record = UniverseConfig(
                ticker=data["ticker"],
                name=data["name"],
                exchange=data["exchange"],
                sector=data["sector"],
                leverage=data["leverage"],
                is_inverse=data["is_inverse"],
                pair_ticker=data["pair_ticker"],
                enabled=data["enabled"],
            )
            session.add(record)  # type: ignore[union-attr]
            seeded.append(data)

        # get_session 컨텍스트 매니저가 자동으로 커밋한다
        logger.info("하드코딩 데이터 시드 완료: %d개 티커", len(seeded))
        return seeded

    async def save_ticker(self, ticker_data: dict) -> None:
        """단일 티커를 DB에 저장(UPSERT)한다.

        동일 ticker가 존재하면 업데이트, 없으면 신규 삽입한다.

        Args:
            ticker_data: TickerMeta.model_dump() 형식의 딕셔너리이다.
        """
        from src.db.models import UniverseConfig

        ticker = ticker_data.get("ticker", "")
        try:
            async with self._db.get_session() as session:
                result = await session.execute(
                    select(UniverseConfig).where(UniverseConfig.ticker == ticker)
                )
                existing = result.scalar_one_or_none()

                if existing is not None:
                    # 기존 레코드를 업데이트한다
                    for field in _TICKER_FIELDS:
                        if field in ticker_data and field != "ticker":
                            setattr(existing, field, ticker_data[field])
                    logger.info("유니버스 DB 업데이트: %s", ticker)
                else:
                    # 신규 레코드를 삽입한다
                    record = UniverseConfig(
                        ticker=ticker_data.get("ticker", ""),
                        name=ticker_data.get("name", ""),
                        exchange=ticker_data.get("exchange", "AMS"),
                        sector=ticker_data.get("sector", "broad_market"),
                        leverage=ticker_data.get("leverage", 2.0),
                        is_inverse=ticker_data.get("is_inverse", False),
                        pair_ticker=ticker_data.get("pair_ticker"),
                        enabled=ticker_data.get("enabled", True),
                    )
                    session.add(record)
                    logger.info("유니버스 DB 삽입: %s", ticker)

        except Exception:
            logger.exception("유니버스 DB 저장 실패: %s", ticker)

    async def delete_ticker(self, ticker: str) -> bool:
        """DB에서 티커를 삭제한다.

        Args:
            ticker: 삭제할 티커 심볼이다.

        Returns:
            삭제 성공 시 True, 대상 없거나 실패 시 False이다.
        """
        from src.db.models import UniverseConfig

        try:
            async with self._db.get_session() as session:
                result = await session.execute(
                    delete(UniverseConfig).where(UniverseConfig.ticker == ticker)
                )
                deleted = result.rowcount > 0  # type: ignore[union-attr]
                if deleted:
                    logger.info("유니버스 DB 삭제: %s", ticker)
                else:
                    logger.warning("유니버스 DB 삭제 대상 없음: %s", ticker)
                return deleted

        except Exception:
            logger.exception("유니버스 DB 삭제 실패: %s", ticker)
            return False

    async def toggle_ticker(self, ticker: str, enabled: bool) -> bool:
        """티커 활성 상태를 변경한다.

        Args:
            ticker: 대상 티커 심볼이다.
            enabled: 활성화 여부이다.

        Returns:
            변경 성공 시 True, 대상 없거나 실패 시 False이다.
        """
        from src.db.models import UniverseConfig

        try:
            async with self._db.get_session() as session:
                result = await session.execute(
                    update(UniverseConfig)
                    .where(UniverseConfig.ticker == ticker)
                    .values(enabled=enabled)
                )
                updated = result.rowcount > 0  # type: ignore[union-attr]
                if updated:
                    logger.info("유니버스 DB 토글: %s -> enabled=%s", ticker, enabled)
                else:
                    logger.warning("유니버스 DB 토글 대상 없음: %s", ticker)
                return updated

        except Exception:
            logger.exception("유니버스 DB 토글 실패: %s", ticker)
            return False

    @staticmethod
    def _row_to_dict(row: object) -> dict:
        """ORM 레코드를 딕셔너리로 변환한다."""
        return {
            "ticker": row.ticker,  # type: ignore[attr-defined]
            "name": row.name,  # type: ignore[attr-defined]
            "exchange": row.exchange,  # type: ignore[attr-defined]
            "sector": row.sector,  # type: ignore[attr-defined]
            "leverage": row.leverage,  # type: ignore[attr-defined]
            "is_inverse": row.is_inverse,  # type: ignore[attr-defined]
            "pair_ticker": row.pair_ticker,  # type: ignore[attr-defined]
            "enabled": row.enabled,  # type: ignore[attr-defined]
        }
