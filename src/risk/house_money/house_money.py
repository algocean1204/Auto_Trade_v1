"""HouseMoneyMultiplier (F6.17) -- 일일 PnL 기반 포지션 배수이다.

당일 수익이 많으면 공격적으로, 손실이 크면 방어적으로
포지션 크기를 조절한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.risk.models import MultiplierResult

_logger = get_logger(__name__)

# -- PnL 구간별 배수 및 라벨 --
_BANDS: list[tuple[float, float, str]] = [
    # (하한(%), 배수, 구간 이름)
    (2.0, 2.0, "max_aggressive"),
    (0.0, 1.5, "aggressive"),
    (-2.0, 1.0, "normal"),
    (float("-inf"), 0.5, "defensive"),
]


def calculate_multiplier(
    daily_pnl_pct: float,
) -> MultiplierResult:
    """일일 PnL 기준 포지션 배수를 결정한다.

    Args:
        daily_pnl_pct: 당일 누적 손익(%).

    Returns:
        배수(0.5x~2.0x)와 PnL 구간 라벨.
    """
    multiplier, band = _resolve_band(daily_pnl_pct)

    _logger.debug(
        "HouseMoney: PnL=%.2f%% -> %.1fx (%s)",
        daily_pnl_pct, multiplier, band,
    )

    return MultiplierResult(
        multiplier=multiplier,
        pnl_band=band,
    )


def _resolve_band(
    pnl_pct: float,
) -> tuple[float, str]:
    """PnL에 해당하는 배수 구간을 찾는다."""
    for threshold, mult, name in _BANDS:
        if pnl_pct >= threshold:
            return mult, name
    # fallback: 최하위 구간
    return 0.5, "defensive"
