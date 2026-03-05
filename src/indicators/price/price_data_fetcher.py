"""F3 지표 -- KIS API 일봉 가격 데이터 조회이다."""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient, OHLCV
from src.common.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_DAYS: int = 100


class PriceDataFetcher:
    """KIS API로 일봉 가격 데이터를 조회한다.

    BrokerClient.get_daily_candles를 래핑하여 유효성 검증 후 반환한다.
    """

    def __init__(self, broker: BrokerClient) -> None:
        """BrokerClient 의존성을 주입받는다."""
        self._broker = broker

    async def fetch(
        self, ticker: str, days: int = _DEFAULT_DAYS, exchange: str = "NAS",
    ) -> list[OHLCV]:
        """일봉 캔들 데이터를 조회하여 날짜 오름차순으로 반환한다."""
        candles = await self._safe_fetch(ticker, days, exchange)
        if not candles:
            return []
        sorted_candles = sorted(candles, key=lambda c: c.date)
        logger.debug("%s 일봉 %d개 조회 완료", ticker, len(sorted_candles))
        return sorted_candles

    async def _safe_fetch(
        self, ticker: str, days: int, exchange: str,
    ) -> list[OHLCV]:
        """브로커에서 일봉을 조회한다. 실패 시 빈 리스트를 반환한다."""
        try:
            candles = await self._broker.get_daily_candles(ticker, days=days, exchange=exchange)
        except Exception:
            logger.exception("일봉 조회 실패: %s", ticker)
            return []
        if not candles:
            logger.warning("일봉 데이터 없음: %s (days=%d)", ticker, days)
        return candles or []
