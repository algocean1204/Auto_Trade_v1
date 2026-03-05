"""F3 지표 -- MACD 다이버전스 분석이다."""
from __future__ import annotations

import numpy as np

from src.common.broker_gateway import OHLCV
from src.common.logger import get_logger
from src.indicators.models import DivergenceSignal
from src.indicators.technical.technical_calculator import _ema_series

logger = get_logger(__name__)

_MIN_CANDLES: int = 30
_LOOKBACK: int = 20
_PIVOT_WINDOW: int = 3


def _find_peaks(data: np.ndarray, window: int) -> list[tuple[int, float]]:
    """로컬 고점의 (인덱스, 값) 리스트를 반환한다."""
    peaks: list[tuple[int, float]] = []
    for i in range(window, len(data) - window):
        segment = data[i - window : i + window + 1]
        if data[i] == np.max(segment):
            peaks.append((i, float(data[i])))
    return peaks


def _find_troughs(data: np.ndarray, window: int) -> list[tuple[int, float]]:
    """로컬 저점의 (인덱스, 값) 리스트를 반환한다."""
    troughs: list[tuple[int, float]] = []
    for i in range(window, len(data) - window):
        segment = data[i - window : i + window + 1]
        if data[i] == np.min(segment):
            troughs.append((i, float(data[i])))
    return troughs


def _calc_macd_line(closes: np.ndarray) -> np.ndarray:
    """MACD 라인 시리즈를 계산한다."""
    fast = _ema_series(closes, 12)
    slow = _ema_series(closes, 26)
    return fast - slow


def _detect_bullish(
    price_troughs: list[tuple[int, float]],
    macd_troughs: list[tuple[int, float]],
) -> tuple[float, float]:
    """강세 다이버전스를 탐지한다. 가격 하락 + MACD 상승 패턴이다."""
    if len(price_troughs) < 2 or len(macd_troughs) < 2:
        return 0.0, 0.0
    p1, p2 = price_troughs[-2], price_troughs[-1]
    m1, m2 = macd_troughs[-2], macd_troughs[-1]
    # 가격은 하락했지만 MACD는 상승한 경우
    if p2[1] < p1[1] and m2[1] > m1[1]:
        strength = (m2[1] - m1[1]) / max(abs(m1[1]), 0.0001)
        price_diff = (p1[1] - p2[1]) / p1[1]
        confidence = min(1.0, (strength + price_diff) * 2.0)
        return min(1.0, strength), confidence
    return 0.0, 0.0


def _detect_bearish(
    price_peaks: list[tuple[int, float]],
    macd_peaks: list[tuple[int, float]],
) -> tuple[float, float]:
    """약세 다이버전스를 탐지한다. 가격 상승 + MACD 하락 패턴이다."""
    if len(price_peaks) < 2 or len(macd_peaks) < 2:
        return 0.0, 0.0
    p1, p2 = price_peaks[-2], price_peaks[-1]
    m1, m2 = macd_peaks[-2], macd_peaks[-1]
    # 가격은 상승했지만 MACD는 하락한 경우
    if p2[1] > p1[1] and m2[1] < m1[1]:
        strength = (m1[1] - m2[1]) / max(abs(m1[1]), 0.0001)
        price_diff = (p2[1] - p1[1]) / p1[1]
        confidence = min(1.0, (strength + price_diff) * 2.0)
        return min(1.0, strength), confidence
    return 0.0, 0.0


class MACDDivergence:
    """MACD 다이버전스(강세/약세)를 분석한다."""

    def analyze(self, candles: list[OHLCV]) -> DivergenceSignal:
        """캔들 데이터로부터 MACD 다이버전스를 판별한다."""
        if len(candles) < _MIN_CANDLES:
            return DivergenceSignal(type="none", strength=0.0, confidence=0.0)
        closes = np.array([c.close for c in candles], dtype=float)
        macd_line = _calc_macd_line(closes)
        pivots = self._extract_pivots(closes[-_LOOKBACK:], macd_line[-_LOOKBACK:])
        result = self._classify(*pivots)
        logger.debug("MACD 다이버전스: %s (str=%.4f)", result.type, result.strength)
        return result

    def _extract_pivots(
        self, close: np.ndarray, macd: np.ndarray,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """가격/MACD 피봇에서 강세/약세 점수를 추출한다."""
        bull = _detect_bullish(_find_troughs(close, _PIVOT_WINDOW), _find_troughs(macd, _PIVOT_WINDOW))
        bear = _detect_bearish(_find_peaks(close, _PIVOT_WINDOW), _find_peaks(macd, _PIVOT_WINDOW))
        return bull, bear

    def _classify(
        self, bull: tuple[float, float], bear: tuple[float, float],
    ) -> DivergenceSignal:
        """강세/약세 중 강한 쪽을 선택하여 DivergenceSignal을 생성한다."""
        if bull[0] > bear[0]:
            return DivergenceSignal(type="bullish", strength=round(bull[0], 4), confidence=round(bull[1], 4))
        if bear[0] > 0:
            return DivergenceSignal(type="bearish", strength=round(bear[0], 4), confidence=round(bear[1], 4))
        return DivergenceSignal(type="none", strength=0.0, confidence=0.0)
