"""RiskBudget (F6.13) -- Kelly Criterion 포지션 사이징이다.

승률과 평균 손익을 기반으로 최적 포지션 크기를 계산한다.
Fractional Kelly (25%)를 적용하고 최대 25%로 캡한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.risk.models import PositionSizeResult

_logger = get_logger(__name__)

# -- 상수 --
_FRACTIONAL_KELLY: float = 0.25
_MAX_POSITION_PCT: float = 25.0
_MIN_WIN_RATE: float = 0.01
_MIN_AVG_WIN: float = 0.01


def calculate_position_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    total_capital: float,
) -> PositionSizeResult:
    """Kelly Criterion으로 최적 포지션 크기를 계산한다.

    Args:
        win_rate: 승률 (0.0~1.0).
        avg_win: 평균 이익(%). 양수.
        avg_loss: 평균 손실(%). 양수(절대값).
        total_capital: 총 자본(USD).

    Returns:
        Kelly 비율, 조정된 비율, 최대 포지션 금액.
    """
    kelly_pct = _compute_kelly(win_rate, avg_win, avg_loss)
    adjusted_pct = _apply_fractional_cap(kelly_pct)
    max_position = total_capital * (adjusted_pct / 100)

    _logger.debug(
        "Kelly: %.2f%% -> 조정: %.2f%% (자본 $%.0f -> $%.0f)",
        kelly_pct, adjusted_pct, total_capital, max_position,
    )

    return PositionSizeResult(
        kelly_pct=round(kelly_pct, 4),
        adjusted_pct=round(adjusted_pct, 4),
        max_position=round(max_position, 2),
    )


def _compute_kelly(
    win_rate: float, avg_win: float, avg_loss: float,
) -> float:
    """Kelly 공식을 계산한다.

    Kelly = (W * avg_win - (1-W) * avg_loss) / avg_win
    음수이면 베팅하지 않는 것이 최적이므로 0으로 클램프한다.
    """
    if win_rate < _MIN_WIN_RATE or avg_win < _MIN_AVG_WIN:
        return 0.0

    loss_rate = 1.0 - win_rate
    numerator = win_rate * avg_win - loss_rate * avg_loss
    kelly = (numerator / avg_win) * 100

    return max(kelly, 0.0)


def _apply_fractional_cap(kelly_pct: float) -> float:
    """Fractional Kelly(25%)를 적용하고 최대 25%로 캡한다."""
    fractional = kelly_pct * _FRACTIONAL_KELLY
    return min(fractional, _MAX_POSITION_PCT)
