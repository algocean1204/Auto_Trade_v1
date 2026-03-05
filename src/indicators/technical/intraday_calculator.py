"""F3 지표 -- VWAP, 장중 RSI, 볼린저 계산이다."""
from __future__ import annotations

import numpy as np

from src.common.logger import get_logger
from src.indicators.models import Candle5m, IntradayIndicators
from src.indicators.technical.technical_calculator import calc_bollinger, calc_rsi

logger = get_logger(__name__)

_MIN_CANDLES: int = 5


def _calc_vwap(candles: list[Candle5m]) -> float:
    """VWAP(거래량 가중 평균가)를 계산한다."""
    typical_prices = np.array(
        [(c.high + c.low + c.close) / 3.0 for c in candles], dtype=float,
    )
    volumes = np.array([c.volume for c in candles], dtype=float)
    total_volume = np.sum(volumes)
    if total_volume == 0:
        return float(np.mean(typical_prices))
    return float(np.sum(typical_prices * volumes) / total_volume)


class IntradayCalculator:
    """5분봉 데이터로 장중 지표(VWAP, RSI, 볼린저)를 계산한다."""

    def calculate(self, candles: list[Candle5m]) -> IntradayIndicators:
        """장중 지표를 산출한다.

        Args:
            candles: 시간 오름차순 Candle5m 리스트

        Returns:
            IntradayIndicators 결과
        """
        if len(candles) < _MIN_CANDLES:
            logger.warning("장중 캔들 부족: %d < %d", len(candles), _MIN_CANDLES)

        closes = np.array([c.close for c in candles], dtype=float)
        vwap = _calc_vwap(candles)
        intraday_rsi = calc_rsi(closes, period=14)
        bb_upper, bb_mid, bb_lower = calc_bollinger(closes, period=20, std_dev=2.0)

        logger.debug(
            "장중 지표: VWAP=%.2f, RSI=%.2f, BB=%.2f/%.2f/%.2f",
            vwap, intraday_rsi, bb_upper, bb_mid, bb_lower,
        )
        return IntradayIndicators(
            vwap=round(vwap, 4),
            intraday_rsi=round(intraday_rsi, 2),
            bb_upper=round(bb_upper, 4),
            bb_middle=round(bb_mid, 4),
            bb_lower=round(bb_lower, 4),
        )
