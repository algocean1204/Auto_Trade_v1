"""FS 스캘핑 매니저 -- 유동성/스푸핑/시간 분석을 오케스트레이션한다.

호가창 데이터와 주문 흐름을 종합 분석하여
스캘핑 진입 가능 여부와 조정된 포지션 크기를 결정한다.
"""
from __future__ import annotations

from datetime import datetime

from src.common.logger import get_logger
from src.scalping.liquidity.depth_analyzer import analyze_depth
from src.scalping.liquidity.impact_estimator import estimate_impact
from src.scalping.liquidity.spread_monitor import SpreadMonitor
from src.scalping.models import ScalpingDecision
from src.scalping.spoofing.spoofing_detector import detect_spoofing
from src.scalping.time_stop.time_stop_manager import TimeStopManager

_logger = get_logger(__name__)

# 스캘핑 진입 차단 임계값이다
_MIN_DEPTH_SCORE = 0.1       # 최소 유동성 깊이
_MAX_SPREAD_Z = 2.5           # 스프레드 Z-Score 상한
_MAX_SLIPPAGE_PCT = 1.0       # 최대 허용 슬리피지 (%)
_SPOOFING_SIZE_REDUCTION = 0.5  # 스푸핑 감지 시 사이즈 축소 비율


class ScalpingManager:
    """스캘핑 종합 판단 매니저이다.

    유동성 깊이, 스프레드, 시장 충격, 스푸핑을 종합하여
    진입 가능 여부와 조정된 포지션 크기를 결정한다.
    """

    def __init__(
        self,
        max_hold_seconds: int = 120,
    ) -> None:
        """스프레드 모니터와 시간 정지 매니저를 초기화한다."""
        self._spread_monitor = SpreadMonitor()
        self._time_stop = TimeStopManager(max_hold_seconds)
        self._orderbook_history: list[dict] = []

    def evaluate(
        self,
        ticker: str,
        orderbook: dict,
        order_size: int,
        price: float = 0.0,
    ) -> ScalpingDecision:
        """스캘핑 진입 가능 여부를 종합 판단한다."""
        warnings: list[str] = []
        size_multiplier = 1.0
        # 1. 호가창 깊이 분석한다
        depth = analyze_depth(orderbook)
        if depth.depth_score < _MIN_DEPTH_SCORE:
            return ScalpingDecision(
                safe_to_trade=False,
                adjusted_size=0.0,
                warnings=[f"유동성 부족: depth_score={depth.depth_score}"],
            )
        # 2. 스프레드 확인한다
        spread = self._spread_monitor.update(orderbook)
        if spread.spread_z_score > _MAX_SPREAD_Z:
            warnings.append(f"스프레드 확대: z={spread.spread_z_score:.2f}")
            size_multiplier *= 0.7
        # 3. 시장 충격 추정한다
        impact = estimate_impact(order_size, depth, price)
        if impact.expected_slippage_pct > _MAX_SLIPPAGE_PCT:
            warnings.append(f"슬리피지 과대: {impact.expected_slippage_pct:.2f}%")
            size_multiplier *= 0.5
        # 4. 스푸핑 탐지한다
        self._orderbook_history.append(orderbook)
        if len(self._orderbook_history) > 20:
            self._orderbook_history = self._orderbook_history[-20:]
        spoofing = detect_spoofing(self._orderbook_history)
        if spoofing.detected:
            warnings.append(f"스푸핑 감지: {spoofing.pattern_type}")
            size_multiplier *= _SPOOFING_SIZE_REDUCTION
        adjusted = max(1.0, order_size * size_multiplier)
        safe = len(warnings) <= 1  # 경고 2개 이상이면 위험이다
        _logger.debug(
            "%s 스캘핑 판단: safe=%s, size=%.0f, warnings=%d",
            ticker, safe, adjusted, len(warnings),
        )
        return ScalpingDecision(
            safe_to_trade=safe,
            adjusted_size=round(adjusted, 0),
            warnings=warnings,
        )

    def check_time_stop(
        self, entry_time: datetime,
    ) -> bool:
        """포지션의 시간 초과 여부를 확인한다."""
        result = self._time_stop.check(entry_time)
        return result.should_exit

    def reset(self) -> None:
        """내부 상태를 초기화한다. EOD 또는 포지션 종료 시 호출한다."""
        self._orderbook_history.clear()
        self._spread_monitor = SpreadMonitor()
        _logger.debug("ScalpingManager 상태 초기화")
