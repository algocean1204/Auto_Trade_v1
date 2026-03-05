"""F3 지표 -- 레버리지 디케이 (변동성 드래그) 정량화이다."""
from __future__ import annotations

import numpy as np

from src.common.broker_gateway import OHLCV
from src.common.logger import get_logger
from src.indicators.models import DecayScore

logger = get_logger(__name__)

_FORCE_EXIT_THRESHOLD: float = 5.0  # 5% 이상 디케이 시 강제 청산 권고
_MIN_CANDLES: int = 5


def _calc_daily_returns(closes: np.ndarray) -> np.ndarray:
    """일간 수익률 시리즈를 계산한다."""
    if len(closes) < 2:
        return np.array([0.0])
    return np.diff(closes) / closes[:-1]


def _calc_compounded_return(returns: np.ndarray) -> float:
    """복리 수익률을 계산한다."""
    return float(np.prod(1.0 + returns) - 1.0)


def _calc_leveraged_compound(returns: np.ndarray, leverage: float) -> float:
    """레버리지 적용 복리 수익률을 계산한다.

    일간 수익률에 레버리지를 곱한 후 복리 누적한다.
    실제 레버리지 ETF의 일간 리밸런싱 메커니즘을 시뮬레이션한다.
    """
    leveraged_returns = returns * leverage
    return float(np.prod(1.0 + leveraged_returns) - 1.0)


def _calc_ideal_return(total_return: float, leverage: float) -> float:
    """레버리지 없는 이상적 수익률을 계산한다.

    기초자산 누적 수익률 × 레버리지 = 디케이 없는 이상 수익률이다.
    """
    return total_return * leverage


def _calc_decay_pct(ideal: float, actual: float) -> float:
    """이상 수익률 대비 실제 수익률의 디케이 비율(%)을 계산한다.

    양수 = 디케이 발생 (실제 < 이상), 음수 = 오히려 초과 수익이다.
    """
    if abs(ideal) < 0.0001:
        return 0.0
    return (ideal - actual) / abs(ideal) * 100.0


class LeverageDecay:
    """레버리지 ETF의 변동성 드래그를 정량화한다."""

    def calculate(self, candles: list[OHLCV], leverage: float = 2.0) -> DecayScore:
        """레버리지 디케이를 산출한다. 5% 초과 시 강제 청산을 권고한다."""
        if len(candles) < _MIN_CANDLES:
            return DecayScore(decay_pct=0.0, force_exit=False)
        closes = np.array([c.close for c in candles], dtype=float)
        returns = _calc_daily_returns(closes)
        ideal = _calc_ideal_return(_calc_compounded_return(returns), leverage)
        actual = _calc_leveraged_compound(returns, leverage)
        decay = _calc_decay_pct(ideal, actual)
        logger.debug("디케이: ideal=%.4f, actual=%.4f, decay=%.2f%%", ideal, actual, decay)
        return DecayScore(decay_pct=round(decay, 4), force_exit=decay > _FORCE_EXIT_THRESHOLD)
