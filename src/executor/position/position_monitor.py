"""PositionMonitor (F5.4) -- 보유 포지션을 동기화하고 모니터링한다.

KIS API에서 실시간 포지션 데이터를 가져와 로컬 캐시를 유지한다.
다른 모듈은 캐시된 포지션에 빠르게 접근할 수 있다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.broker_gateway import (
    BrokerClient,
    PositionData,
)
from src.common.error_handler import BrokerError
from src.common.logger import get_logger

logger = get_logger(__name__)


class PositionMonitor:
    """포지션 모니터이다.

    KIS에서 보유 포지션을 주기적으로 동기화하고,
    캐시된 데이터를 통해 빠른 조회를 지원한다.
    """

    def __init__(self, broker: BrokerClient) -> None:
        """BrokerClient를 주입받아 초기화한다."""
        self._broker = broker
        self._positions: dict[str, PositionData] = {}
        self._last_sync: datetime | None = None
        logger.info("PositionMonitor 초기화 완료")

    async def sync_positions(self) -> dict[str, PositionData]:
        """KIS에서 현재 보유 포지션을 동기화한다.

        잔고 API를 호출하여 캐시를 갱신하고 결과를 반환한다.
        API 오류 시 기존 캐시를 유지하여 데이터 손실을 방지한다.
        """
        try:
            balance = await self._broker.get_balance()
            new_positions: dict[str, PositionData] = {}
            for pos in balance.positions:
                new_positions[pos.ticker] = pos
            self._positions = new_positions
            self._last_sync = datetime.now(tz=timezone.utc)
            logger.info(
                "포지션 동기화 완료: %d개 종목", len(self._positions),
            )
        except BrokerError as exc:
            # API 오류 시 기존 캐시를 덮어쓰지 않는다 — 경과 시간에 따라 로그 레벨 분기한다
            if self._last_sync is not None:
                age = (datetime.now(tz=timezone.utc) - self._last_sync).total_seconds()
                if age > 300:  # 5분
                    logger.error(
                        "포지션 캐시 %.0f초 경과 (5분 초과) — 데이터 신뢰도 낮음", age,
                    )
                else:
                    logger.warning(
                        "포지션 동기화 실패 (캐시 %.0f초): %s", age, exc.message,
                    )
            else:
                logger.error("포지션 동기화 최초 실패: %s", exc.message)
        return dict(self._positions)

    async def get_position(self, ticker: str) -> PositionData | None:
        """특정 종목의 포지션을 반환한다.

        캐시가 비어있으면 먼저 동기화를 시도한다.
        """
        if not self._positions:
            await self.sync_positions()
        return self._positions.get(ticker)

    def get_all_positions(self) -> dict[str, PositionData]:
        """캐시된 전체 포지션을 반환한다."""
        return dict(self._positions)

    def get_position_count(self) -> int:
        """보유 종목 수를 반환한다."""
        return len(self._positions)

    def get_total_value(self) -> float:
        """전체 포지션의 평가 금액 합계를 반환한다."""
        return sum(
            pos.current_price * pos.quantity
            for pos in self._positions.values()
        )

    def get_last_sync_time(self) -> datetime | None:
        """마지막 동기화 시각을 반환한다."""
        return self._last_sync

    def has_position(self, ticker: str) -> bool:
        """해당 종목의 포지션을 보유 중인지 확인한다."""
        return ticker in self._positions

    async def verify_and_sync(self) -> dict[str, int]:
        """브로커 실잔고와 캐시를 비교하여 불일치를 감지하고 동기화한다.

        불일치 발견 시 로그를 남기고 캐시를 갱신한다.
        Returns:
            불일치 종목별 차이 (캐시 수량 - 실제 수량). 빈 dict이면 일치.
        """
        old_positions = dict(self._positions)
        await self.sync_positions()
        mismatches: dict[str, int] = {}
        all_tickers = set(old_positions.keys()) | set(self._positions.keys())
        for ticker in all_tickers:
            old_qty = old_positions.get(ticker)
            new_qty = self._positions.get(ticker)
            cached = old_qty.quantity if old_qty else 0
            actual = new_qty.quantity if new_qty else 0
            if cached != actual:
                mismatches[ticker] = cached - actual
                logger.warning(
                    "포지션 불일치: %s 캐시=%d주, 실제=%d주 (차이=%+d)",
                    ticker, cached, actual, cached - actual,
                )
        if not mismatches:
            logger.debug("포지션 검증 완료: 불일치 없음")
        return mismatches

    def clear_cache(self) -> None:
        """포지션 캐시를 초기화한다. 테스트/EOD용이다."""
        self._positions.clear()
        self._last_sync = None
        logger.info("포지션 캐시 초기화 완료")
