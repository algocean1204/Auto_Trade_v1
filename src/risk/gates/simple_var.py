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

# -- VaR 기반 포지션 조정 임계값 --
# VaR이 포트폴리오의 이 비율을 초과하면 포지션 축소 배수를 적용한다
_VAR_WARNING_THRESHOLD_PCT: float = 5.0
# 임계값 초과 시 적용할 최소 포지션 축소 배수 (0.7 = 30% 축소)
_VAR_REDUCTION_MULTIPLIER: float = 0.7


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


def get_var_position_multiplier(
    portfolio_value: float,
    daily_returns: list[float],
) -> float:
    """VaR 기반 포지션 사이즈 조정 배수를 반환한다.

    포트폴리오 VaR이 총 가치의 5%를 초과하면 경고를 기록하고
    축소 배수(0.7)를 반환한다. 정상 범위이면 1.0을 반환한다.
    차단하지 않고 권고(advisory)로만 동작한다.

    Args:
        portfolio_value: 포트폴리오 총 가치(USD).
        daily_returns: 일일 수익률(%) 리스트.

    Returns:
        포지션 축소 배수 (1.0 = 변동 없음, <1.0 = 축소 권고).
    """
    if portfolio_value <= 0:
        return 1.0

    result = calculate_var(portfolio_value, daily_returns)
    if result.var_99 <= 0:
        return 1.0

    var_pct_of_portfolio = (result.var_99 / portfolio_value) * 100.0

    if var_pct_of_portfolio > _VAR_WARNING_THRESHOLD_PCT:
        _logger.warning(
            "[VaR경고] 포트폴리오 VaR %.2f%% > 임계값 %.1f%% "
            "(VaR=$%.2f, ES=$%.2f) -- 포지션 축소 배수 %.2f 적용",
            var_pct_of_portfolio, _VAR_WARNING_THRESHOLD_PCT,
            result.var_99, result.expected_shortfall,
            _VAR_REDUCTION_MULTIPLIER,
        )
        return _VAR_REDUCTION_MULTIPLIER

    return 1.0


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
