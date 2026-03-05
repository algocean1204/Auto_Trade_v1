"""FS 스프레드 모니터 -- 실시간 매수/매도 스프레드를 추적한다.

현재 스프레드, 평균 스프레드, Z-Score를 계산하여
비정상적 스프레드 확대를 감지한다.
"""
from __future__ import annotations

import math
from collections import deque

from src.common.logger import get_logger
from src.scalping.models import SpreadState

_logger = get_logger(__name__)

# 스프레드 이력 최대 보관 수이다
_MAX_HISTORY = 200
# Z-Score 계산을 위한 최소 샘플 수이다
_MIN_SAMPLES = 10


class SpreadMonitor:
    """실시간 스프레드 추적 모니터이다.

    호가창 데이터를 받아 스프레드를 계산하고,
    이력 기반 Z-Score로 비정상 확대를 감지한다.
    """

    def __init__(self, max_history: int = _MAX_HISTORY) -> None:
        """이력 저장소를 초기화한다."""
        self._history: deque[float] = deque(maxlen=max_history)

    def update(self, orderbook: dict) -> SpreadState:
        """호가창으로 현재 스프레드를 계산하고 상태를 반환한다."""
        current = self._calculate_spread(orderbook)
        self._history.append(current)
        avg = self._calculate_average()
        z_score = self._calculate_z_score(current, avg)
        return SpreadState(
            current_spread=round(current, 6),
            avg_spread=round(avg, 6),
            spread_z_score=round(z_score, 4),
        )

    def _calculate_spread(self, orderbook: dict) -> float:
        """최우선 매수/매도 호가로 스프레드(%)를 계산한다."""
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        if not bids or not asks:
            return 0.0
        best_bid = self._get_best_price(bids)
        best_ask = self._get_best_price(asks)
        if best_bid <= 0 or best_ask <= 0:
            return 0.0
        mid = (best_bid + best_ask) / 2.0
        if mid <= 0:
            return 0.0
        return ((best_ask - best_bid) / mid) * 100.0

    def _get_best_price(self, levels: list[dict]) -> float:
        """호가 단계 중 최우선 가격을 반환한다."""
        if not levels:
            return 0.0
        first = levels[0]
        try:
            return float(first.get("price", 0))
        except (ValueError, TypeError):
            return 0.0

    def _calculate_average(self) -> float:
        """이력의 평균 스프레드를 반환한다."""
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history)

    def _calculate_z_score(
        self, current: float, avg: float,
    ) -> float:
        """현재 스프레드의 Z-Score를 계산한다."""
        if len(self._history) < _MIN_SAMPLES:
            return 0.0
        std = self._calculate_std()
        if std < 1e-8:
            return 0.0
        return (current - avg) / std

    def _calculate_std(self) -> float:
        """이력의 표준편차를 반환한다."""
        if len(self._history) < 2:
            return 0.0
        avg = sum(self._history) / len(self._history)
        variance = sum((x - avg) ** 2 for x in self._history) / (len(self._history) - 1)
        return math.sqrt(variance)

    @property
    def sample_count(self) -> int:
        """현재 이력 샘플 수를 반환한다."""
        return len(self._history)
