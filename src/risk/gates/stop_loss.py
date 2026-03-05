"""StopLossManager (F6.15) -- ATR 동적 손절가 + 트레일링이다.

레짐별 ATR 배수로 손절가를 계산하고, 1.5% 이상 수익 시
손절가를 진입가로 이동(break-even stop)한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.risk.models import StopLossResult

_logger = get_logger(__name__)

# -- 레짐별 ATR 배수 --
_ATR_MULTIPLIERS: dict[str, float] = {
    "strong_bull": 3.0,
    "mild_bull": 2.5,
    "sideways": 2.0,
    "mild_bear": 1.5,
    "crash": 1.0,
}

# -- Break-even 진입 기준(%) --
_BREAK_EVEN_THRESHOLD: float = 1.5
_DEFAULT_REGIME: str = "sideways"


def calculate_stop_loss(
    entry_price: float,
    current_price: float,
    atr: float,
    regime: str = _DEFAULT_REGIME,
    regime_trailing_pct: float = 2.5,
) -> StopLossResult:
    """ATR 기반 동적 손절가를 계산한다.

    Args:
        entry_price: 진입가(USD).
        current_price: 현재가(USD).
        atr: ATR 값(USD).
        regime: 시장 레짐. 기본 sideways.
        regime_trailing_pct: 레짐별 트레일링 비율(%).

    Returns:
        손절가, 트레일링 비율, break-even 활성 여부.
    """
    multiplier = _ATR_MULTIPLIERS.get(regime, 2.0)
    atr_stop = _compute_atr_stop(entry_price, atr, multiplier)
    profit_pct = _compute_profit_pct(entry_price, current_price)
    break_even = profit_pct >= _BREAK_EVEN_THRESHOLD

    # break-even이면 최소 손절가를 진입가로 올린다
    stop_price = atr_stop
    if break_even:
        stop_price = max(stop_price, entry_price)

    # 트레일링 스톱: 현재가 기준
    trailing_stop = _compute_trailing_stop(
        current_price, regime_trailing_pct,
    )
    stop_price = max(stop_price, trailing_stop)

    _logger.debug(
        "StopLoss: entry=$%.2f cur=$%.2f atr=$%.2f "
        "-> stop=$%.2f (regime=%s, BE=%s)",
        entry_price, current_price, atr,
        stop_price, regime, break_even,
    )

    return StopLossResult(
        stop_price=round(stop_price, 4),
        trailing_pct=regime_trailing_pct,
        break_even_active=break_even,
    )


def _compute_atr_stop(
    entry_price: float, atr: float, multiplier: float,
) -> float:
    """ATR 배수 기반 손절가를 계산한다."""
    return entry_price - (atr * multiplier)


def _compute_profit_pct(
    entry_price: float, current_price: float,
) -> float:
    """진입가 대비 현재 수익률(%)을 계산한다."""
    if entry_price <= 0:
        return 0.0
    return ((current_price - entry_price) / entry_price) * 100


def _compute_trailing_stop(
    current_price: float, trailing_pct: float,
) -> float:
    """현재가 기준 트레일링 손절가를 계산한다."""
    return current_price * (1 - trailing_pct / 100)


class StopLossManager:
    """DI용 손절 매니저이다. 엔드포인트에서 참조하는 속성을 제공한다."""

    def __init__(
        self,
        initial_stop_pct: float = 3.0,
        trailing_stop_pct: float = 5.0,
    ) -> None:
        self.initial_stop_pct = initial_stop_pct
        self.trailing_stop_pct = trailing_stop_pct

    def calculate(
        self,
        entry_price: float,
        current_price: float,
        atr: float,
        regime: str = "sideways",
    ) -> StopLossResult:
        """ATR 기반 동적 손절가를 계산한다."""
        return calculate_stop_loss(
            entry_price, current_price, atr, regime, self.trailing_stop_pct,
        )
