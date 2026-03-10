"""KIS API 스로틀러 -- 초당 호출 제한을 준수하는 비동기 속도 제한기이다.

KIS OpenAPI 제한:
- 주문(거래): 초당 1건
- 조회(시세/잔고): 초당 2건

토큰 버킷 방식으로 최소 대기만 수행하여 단타 지연을 최소화한다.
"""
from __future__ import annotations

import asyncio
import time

from src.common.logger import get_logger

logger = get_logger(__name__)

# KIS 공식 제한: 주문 초당 1건, 조회 초당 2건
_ORDER_INTERVAL: float = 1.05   # 주문 간 최소 간격(초) — 여유 50ms
_QUERY_INTERVAL: float = 0.55   # 조회 간 최소 간격(초) — 여유 50ms


class _ChannelThrottle:
    """단일 채널의 최소 간격 보장 스로틀러이다."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """호출 권한을 획득한다. 필요 시 대기하고, 실제 대기 시간(초)을 반환한다."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            wait = self._min_interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
                self._last_call = time.monotonic()
                return wait
            self._last_call = now
            return 0.0


class KisThrottle:
    """KIS API 주문/조회 채널별 속도 제한기이다.

    주문과 조회를 별도 채널로 분리하여 독립적으로 제한한다.
    단타 시나리오: 조회(가격) → 주문 순서에서 조회와 주문이 다른 채널이므로
    연속 호출이 가능하다. 같은 채널 내 연속 호출만 대기가 발생한다.
    """

    def __init__(self) -> None:
        self._order = _ChannelThrottle(_ORDER_INTERVAL)
        self._query = _ChannelThrottle(_QUERY_INTERVAL)

    async def before_order(self) -> None:
        """주문 API 호출 전 속도 제한을 적용한다."""
        waited = await self._order.acquire()
        if waited > 0:
            logger.debug("KIS 주문 스로틀: %.0fms 대기", waited * 1000)

    async def before_query(self) -> None:
        """조회 API 호출 전 속도 제한을 적용한다."""
        waited = await self._query.acquire()
        if waited > 0:
            logger.debug("KIS 조회 스로틀: %.0fms 대기", waited * 1000)


# 싱글톤 인스턴스
_instance: KisThrottle | None = None


def get_kis_throttle() -> KisThrottle:
    """KisThrottle 싱글톤을 반환한다."""
    global _instance
    if _instance is None:
        _instance = KisThrottle()
        logger.info(
            "KisThrottle 초기화 (주문=%.2fs, 조회=%.2fs)",
            _ORDER_INTERVAL, _QUERY_INTERVAL,
        )
    return _instance
