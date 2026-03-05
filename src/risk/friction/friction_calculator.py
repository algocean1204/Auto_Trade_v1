"""FrictionCalculator (F6.16) -- 스프레드 + 슬리피지 마찰 비용이다.

매매 진입 전 마찰 비용을 계산하여 최소 수익 허들을 결정한다.
허들 미달 시 리스크 게이트가 진입을 차단한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.risk.models import FrictionResult

_logger = get_logger(__name__)

# -- 기본값 (bps) --
_DEFAULT_SPREAD_BPS: float = 10.0
_DEFAULT_SLIPPAGE_BPS: float = 5.0
_BPS_TO_PCT: float = 0.01  # 1bps = 0.01%
_HURDLE_MULTIPLIER: float = 2.0


def calculate_friction(
    price: float,
    spread_bps: float = _DEFAULT_SPREAD_BPS,
    slippage_bps: float = _DEFAULT_SLIPPAGE_BPS,
    round_trip: bool = True,
) -> FrictionResult:
    """마찰 비용과 최소 수익 허들을 계산한다.

    Args:
        price: 현재가(USD). 비용 표시용.
        spread_bps: 스프레드(bps). 기본 10bps.
        slippage_bps: 슬리피지(bps). 기본 5bps.
        round_trip: 왕복 기준 여부. 기본 True.

    Returns:
        스프레드 비용, 슬리피지 비용, 총 마찰비용,
        최소 수익 허들(총 마찰 x 2).
    """
    spread_pct = _bps_to_pct(spread_bps)
    slippage_pct = _bps_to_pct(slippage_bps)
    trips = 2 if round_trip else 1

    total = (spread_pct + slippage_pct) * trips
    hurdle = total * _HURDLE_MULTIPLIER

    spread_usd = price * spread_pct / 100 * trips
    slippage_usd = price * slippage_pct / 100 * trips

    _logger.debug(
        "마찰 비용: spread=%.3f%% slip=%.3f%% "
        "total=%.3f%% hurdle=%.3f%% (price=$%.2f)",
        spread_pct * trips, slippage_pct * trips,
        total, hurdle, price,
    )

    return FrictionResult(
        spread_cost=round(spread_usd, 4),
        slippage_cost=round(slippage_usd, 4),
        total_friction=round(total, 4),
        min_gain_hurdle=round(hurdle, 4),
    )


def _bps_to_pct(bps: float) -> float:
    """bps를 퍼센트(%)로 변환한다."""
    return bps * _BPS_TO_PCT
