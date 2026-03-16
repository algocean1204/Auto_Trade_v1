"""LosingStreakDetector (F6.21) -- 연속 손실을 추적한다.

최근 거래 이력에서 연속 손실 횟수와 최대 연패를 계산하여
리스크 수준(low/medium/high/critical)을 판정한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.risk.models import StreakResult

_logger = get_logger(__name__)

# -- 리스크 레벨 경계 --
_MEDIUM_THRESHOLD: int = 3
_HIGH_THRESHOLD: int = 5
_CRITICAL_THRESHOLD: int = 7


def detect_losing_streak(
    trade_history: list[dict],
) -> StreakResult:
    """거래 이력에서 연속 손실을 분석한다.

    Args:
        trade_history: 거래 이력 목록. 각 dict에 pnl(%) 키 필요.
            시간순 정렬(오래된 것부터) 가정.

    Returns:
        현재 연패 수, 최대 연패 수, 리스크 레벨.
    """
    if not trade_history:
        return StreakResult(
            consecutive_losses=0,
            max_streak=0,
            risk_level="low",
        )

    consecutive, max_streak = _count_streaks(trade_history)
    risk_level = _classify_risk(consecutive)

    if risk_level != "low":
        _logger.info(
            "연패 감지: %d연패 (최대 %d) -> %s",
            consecutive, max_streak, risk_level,
        )

    return StreakResult(
        consecutive_losses=consecutive,
        max_streak=max_streak,
        risk_level=risk_level,
    )


def _count_streaks(
    trades: list[dict],
) -> tuple[int, int]:
    """연속 손실 횟수와 최대 연패를 계산한다."""
    current_streak = 0
    max_streak = 0

    for trade in trades:
        # 매수 거래는 pnl이 None이므로 연패 계산에서 제외한다.
        # 매수(buy)가 끼어들어 연패 카운터를 리셋하는 버그를 방지한다.
        if trade.get("side") == "buy":
            continue
        pnl = trade.get("pnl") or 0.0
        if pnl < 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return current_streak, max_streak


def _classify_risk(consecutive: int) -> str:
    """연패 횟수를 리스크 레벨로 분류한다."""
    if consecutive >= _CRITICAL_THRESHOLD:
        return "critical"
    if consecutive >= _HIGH_THRESHOLD:
        return "high"
    if consecutive >= _MEDIUM_THRESHOLD:
        return "medium"
    return "low"


class LosingStreakDetector:
    """DI용 연패 감지기이다. 엔드포인트에서 참조하는 속성을 제공한다."""

    def __init__(self) -> None:
        self.current_streak: int = 0
        self.max_streak: int = 0

    def update(self, trade_history: list[dict]) -> StreakResult:
        """거래 이력으로 연패 상태를 갱신한다."""
        result = detect_losing_streak(trade_history)
        self.current_streak = result.consecutive_losses
        self.max_streak = max(self.max_streak, result.max_streak)
        return result
