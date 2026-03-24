"""FxManager -- USD/KRW 환율을 조회하고 캐싱한다.

BrokerClient.get_exchange_rate()를 호출하여 실시간 환율을 가져온다.
1시간 캐시로 API 호출을 최소화한다.
조회 실패 시 None을 반환한다 (하드코딩 폴백 없음).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.broker_gateway import BrokerClient
from src.common.logger import get_logger
from src.tax.models import FxRate

logger = get_logger(__name__)

# 캐시 유효 시간 (초)
_CACHE_TTL_SEC: int = 3600


class FxManager:
    """USD/KRW 환율 조회 관리자이다. 1시간 캐시를 유지한다."""

    def __init__(self, broker: BrokerClient) -> None:
        """BrokerClient를 주입받는다."""
        self._broker = broker
        self._cached: FxRate | None = None
        logger.info("FxManager 초기화 완료")

    def _is_cache_valid(self) -> bool:
        """캐시가 유효한지 확인한다."""
        if self._cached is None:
            return False
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self._cached.last_updated).total_seconds()
        return elapsed < _CACHE_TTL_SEC

    async def get_rate(self) -> FxRate | None:
        """USD/KRW 환율을 반환한다. 캐시가 유효하면 캐시를 사용한다.

        KIS API에서 받은 환율이 900~2000 범위 밖이면
        유효하지 않은 값으로 판단한다.
        조회 실패 시 이전 캐시가 있으면 캐시를, 없으면 None을 반환한다.
        """
        if self._is_cache_valid():
            return self._cached

        try:
            rate = await self._broker.get_exchange_rate()
            # 범위 검증: 0이거나 비정상 범위이면 실패 처리한다
            if not (900 < rate < 2000):
                logger.warning("KIS 환율 비정상 값: %.2f", rate)
                return self._cached

            self._cached = FxRate(
                usd_krw=rate,
                last_updated=datetime.now(tz=timezone.utc),
            )
            logger.info("환율 갱신: %.2f 원/달러", rate)
        except Exception:
            logger.exception("환율 조회 실패")
            # 이전 캐시가 있으면 만료되어도 반환한다 (없으면 None)
        return self._cached

    async def get_rate_value(self) -> float | None:
        """환율 숫자만 반환한다. 조회 실패 시 None이다."""
        fx = await self.get_rate()
        if fx is None:
            return None
        return fx.usd_krw
