"""F4 미시 레짐 -- 5분봉 기반으로 미시 시장 레짐을 분류한다."""
from __future__ import annotations

import math

from src.common.logger import get_logger
from src.indicators.models import Candle5m
from src.strategy.models import MicroRegimeResult

logger = get_logger(__name__)

# 가중치 상수
_W_ER = 0.35   # Efficiency Ratio
_W_DS = 0.30   # Directional Strength
_W_AC = 0.20   # Autocorrelation
_W_VOL = 0.15  # Volatility

# 레짐 분류 임계값
_TRENDING_THRESHOLD = 0.6
_VOLATILE_THRESHOLD = 0.4
_QUIET_THRESHOLD = 0.2

# 최소 캔들 수
_MIN_CANDLES = 10


def _efficiency_ratio(candles: list[Candle5m]) -> float:
    """ER(Efficiency Ratio)을 계산한다. 방향성 대비 노이즈 비율이다."""
    if len(candles) < 2:
        return 0.0
    net_move = abs(candles[-1].close - candles[0].close)
    total_move = sum(
        abs(candles[i].close - candles[i - 1].close)
        for i in range(1, len(candles))
    )
    if total_move == 0:
        return 0.0
    return round(net_move / total_move, 4)


def _directional_strength(candles: list[Candle5m]) -> float:
    """방향 강도를 계산한다. 상승 캔들 비율 기반이다."""
    if len(candles) < 2:
        return 0.5
    up_count = sum(
        1 for i in range(1, len(candles))
        if candles[i].close > candles[i - 1].close
    )
    ratio = up_count / (len(candles) - 1)
    # 0.5에서 멀어질수록 방향성이 강하다
    return round(abs(ratio - 0.5) * 2, 4)


def _autocorrelation(candles: list[Candle5m]) -> float:
    """1차 자기상관을 계산한다. 추세 지속성을 측정한다."""
    if len(candles) < 3:
        return 0.0
    returns = [
        candles[i].close / candles[i - 1].close - 1
        for i in range(1, len(candles))
        if candles[i - 1].close > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns)
    if var == 0:
        return 0.0
    cov = sum(
        (returns[i] - mean_r) * (returns[i - 1] - mean_r)
        for i in range(1, len(returns))
    )
    return round(cov / var, 4)


def _volatility_score(candles: list[Candle5m]) -> float:
    """변동성 점수를 0~1 범위로 정규화한다."""
    if len(candles) < 2:
        return 0.0
    returns = [
        candles[i].close / candles[i - 1].close - 1
        for i in range(1, len(candles))
        if candles[i - 1].close > 0
    ]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)
    # 연간화 후 정규화 (5분봉 기준, 거래일 252일, 하루 78봉)
    annualized = std * math.sqrt(78 * 252)
    # 0~100% 범위를 0~1로 매핑한다
    return round(min(annualized, 1.0), 4)


def _classify_regime(score: float) -> str:
    """합성 점수로 레짐을 분류한다."""
    if score >= _TRENDING_THRESHOLD:
        return "trending"
    if score >= _VOLATILE_THRESHOLD:
        return "mean_reverting"
    if score >= _QUIET_THRESHOLD:
        return "volatile"
    return "quiet"


class MicroRegime:
    """5분봉 기반 미시 레짐 분류기이다."""

    def evaluate(self, candles_5m: list[Candle5m]) -> MicroRegimeResult:
        """5분봉 데이터로 미시 레짐을 분류한다."""
        if len(candles_5m) < _MIN_CANDLES:
            return MicroRegimeResult(regime="quiet", score=0.0)

        er = _efficiency_ratio(candles_5m)
        ds = _directional_strength(candles_5m)
        ac = _autocorrelation(candles_5m)
        vol = _volatility_score(candles_5m)

        weights = {"er": er, "ds": ds, "ac": ac, "vol": vol}
        score = round(
            _W_ER * er + _W_DS * ds + _W_AC * max(ac, 0) + _W_VOL * vol,
            4,
        )
        regime = _classify_regime(score)

        logger.debug(
            "미시 레짐: %s score=%.4f (ER=%.4f DS=%.4f AC=%.4f VOL=%.4f)",
            regime, score, er, ds, ac, vol,
        )
        return MicroRegimeResult(regime=regime, score=score, weights=weights)
