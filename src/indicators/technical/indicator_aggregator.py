"""F3 지표 -- 기술적 지표 가중합 종합이다."""
from __future__ import annotations

from src.common.logger import get_logger
from src.indicators.models import AggregatedScore, TechnicalIndicators

logger = get_logger(__name__)

# 기본 가중치: RSI(25%), MACD(20%), BB(15%), ATR(15%), EMA(15%), SMA(10%)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "rsi": 0.25,
    "macd": 0.20,
    "bb": 0.15,
    "atr": 0.15,
    "ema": 0.15,
    "sma": 0.10,
}


def _normalize_rsi(rsi: float) -> float:
    """RSI를 -1~+1 범위로 정규화한다. 50 기준 중립이다."""
    return (rsi - 50.0) / 50.0


def _normalize_macd(macd: float, macd_signal: float) -> float:
    """MACD와 Signal 차이를 -1~+1로 클리핑한다."""
    diff = macd - macd_signal
    return max(-1.0, min(1.0, diff * 10.0))


def _normalize_bb(close: float, bb_upper: float, bb_lower: float) -> float:
    """현재가의 볼린저 밴드 내 위치를 -1~+1로 정규화한다."""
    band_width = bb_upper - bb_lower
    if band_width <= 0:
        return 0.0
    position = (close - bb_lower) / band_width
    return (position - 0.5) * 2.0


def _normalize_atr(atr: float, close: float) -> float:
    """ATR을 현재가 대비 비율로 정규화한다. 높을수록 -1에 가깝다(변동성 경고)."""
    if close <= 0:
        return 0.0
    ratio = atr / close
    # ATR/price가 5% 이상이면 극단적 변동성, 0%이면 무변동
    return max(-1.0, min(1.0, -ratio * 20.0))


def _normalize_ema(close: float, ema_20: float, ema_50: float) -> float:
    """EMA 20/50 대비 현재가 위치를 -1~+1로 정규화한다."""
    if ema_50 <= 0:
        return 0.0
    score = 0.0
    # EMA 20 위이면 단기 상승 신호
    score += 0.5 if close > ema_20 else -0.5
    # EMA 50 위이면 중기 상승 신호
    score += 0.5 if close > ema_50 else -0.5
    return score


def _normalize_sma(close: float, sma_200: float) -> float:
    """SMA 200 대비 현재가 위치를 -1~+1로 정규화한다."""
    if sma_200 <= 0:
        return 0.0
    return 1.0 if close > sma_200 else -1.0


class IndicatorAggregator:
    """기술적 지표를 가중합으로 종합한다."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        """가중치를 설정한다. None이면 기본 가중치를 사용한다."""
        self._weights = weights or _DEFAULT_WEIGHTS

    def aggregate(
        self, indicators: TechnicalIndicators, current_close: float | None = None,
    ) -> AggregatedScore:
        """기술적 지표를 가중 종합 점수(-1~+1)로 변환한다."""
        close = current_close or indicators.bb_middle
        components = self._calc_components(indicators, close)
        total = sum(self._weights.get(k, 0.0) * v for k, v in components.items())
        total = max(-1.0, min(1.0, total))
        logger.debug("지표 종합: total=%.4f", total)
        return AggregatedScore(total_score=round(total, 4), components=components)

    def _calc_components(
        self, ind: TechnicalIndicators, close: float,
    ) -> dict[str, float]:
        """개별 지표를 정규화한 컴포넌트 dict를 반환한다."""
        return {
            "rsi": round(_normalize_rsi(ind.rsi), 4),
            "macd": round(_normalize_macd(ind.macd, ind.macd_signal), 4),
            "bb": round(_normalize_bb(close, ind.bb_upper, ind.bb_lower), 4),
            "atr": round(_normalize_atr(ind.atr, close), 4),
            "ema": round(_normalize_ema(close, ind.ema_20, ind.ema_50), 4),
            "sma": round(_normalize_sma(close, ind.sma_200), 4),
        }
