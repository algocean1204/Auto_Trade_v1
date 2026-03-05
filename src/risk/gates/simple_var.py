"""SimpleVaR (F6.12) -- 99% VaR 및 Expected Shortfall을 계산한다.

포트폴리오 일일 수익률 기반 히스토리컬 시뮬레이션 방식이다.
"""

from __future__ import annotations

import numpy as np

from src.common.logger import get_logger
from src.risk.models import VaRResult

_logger = get_logger(__name__)

# -- 상수 --
_VAR_CONFIDENCE: float = 99.0
_MIN_DATA_POINTS: int = 5


def calculate_var(
    portfolio_value: float,
    daily_returns: list[float],
) -> VaRResult:
    """99% VaR과 Expected Shortfall을 계산한다.

    Args:
        portfolio_value: 포트폴리오 총 가치(USD).
        daily_returns: 일일 수익률(%) 리스트.

    Returns:
        VaR 99%와 Expected Shortfall(CVaR). 둘 다 USD 절대값.
    """
    if len(daily_returns) < _MIN_DATA_POINTS:
        _logger.debug(
            "VaR 데이터 부족: %d < %d",
            len(daily_returns), _MIN_DATA_POINTS,
        )
        return VaRResult(var_99=0.0, expected_shortfall=0.0)

    returns_array = np.array(daily_returns, dtype=np.float64)
    var_pct = _compute_percentile_var(returns_array)
    es_pct = _compute_expected_shortfall(returns_array, var_pct)

    # 수익률(%)을 USD 절대값으로 변환
    var_usd = abs(var_pct / 100 * portfolio_value)
    es_usd = abs(es_pct / 100 * portfolio_value)

    _logger.debug(
        "VaR 99%%: $%.2f, ES: $%.2f (포트폴리오 $%.0f)",
        var_usd, es_usd, portfolio_value,
    )

    return VaRResult(
        var_99=round(var_usd, 2),
        expected_shortfall=round(es_usd, 2),
    )


def _compute_percentile_var(
    returns: np.ndarray,
) -> float:
    """1% 분위수(= 99% VaR)를 계산한다."""
    percentile = 100 - _VAR_CONFIDENCE
    return float(np.percentile(returns, percentile))


def _compute_expected_shortfall(
    returns: np.ndarray, var_pct: float,
) -> float:
    """VaR 이하 손실의 평균(Expected Shortfall)을 계산한다."""
    tail_losses = returns[returns <= var_pct]
    if len(tail_losses) == 0:
        return var_pct
    return float(np.mean(tail_losses))
