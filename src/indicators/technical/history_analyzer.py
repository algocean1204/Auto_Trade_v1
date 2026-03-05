"""F3 지표 -- 과거 가격 패턴(지지/저항) 분석이다."""
from __future__ import annotations

import numpy as np

from src.common.broker_gateway import OHLCV
from src.common.logger import get_logger
from src.indicators.models import HistoryPattern

logger = get_logger(__name__)

_MIN_CANDLES: int = 20
_PIVOT_WINDOW: int = 5
_CLUSTER_PCT: float = 0.015  # 1.5% 이내 가격을 동일 클러스터로 묶는다


def _find_local_highs(highs: np.ndarray, window: int) -> list[float]:
    """로컬 고점을 탐색한다. +-window 범위에서 최고점인 인덱스를 찾는다."""
    peaks: list[float] = []
    for i in range(window, len(highs) - window):
        segment = highs[i - window : i + window + 1]
        if highs[i] == np.max(segment):
            peaks.append(float(highs[i]))
    return peaks


def _find_local_lows(lows: np.ndarray, window: int) -> list[float]:
    """로컬 저점을 탐색한다. +-window 범위에서 최저점인 인덱스를 찾는다."""
    troughs: list[float] = []
    for i in range(window, len(lows) - window):
        segment = lows[i - window : i + window + 1]
        if lows[i] == np.min(segment):
            troughs.append(float(lows[i]))
    return troughs


def _cluster_levels(prices: list[float], pct: float) -> list[float]:
    """근접 가격을 클러스터링하여 대표 수준 목록을 반환한다."""
    if not prices:
        return []
    sorted_prices = sorted(prices)
    clusters: list[list[float]] = [[sorted_prices[0]]]
    for price in sorted_prices[1:]:
        center = np.mean(clusters[-1])
        if abs(price - center) / center < pct:
            clusters[-1].append(price)
        else:
            clusters.append([price])
    # 터치 횟수 2회 이상인 클러스터만 유효 수준으로 채택한다
    return [round(float(np.mean(c)), 2) for c in clusters if len(c) >= 2]


def _detect_trend(closes: np.ndarray) -> list[str]:
    """최근 10봉의 추세 패턴을 판별한다."""
    if len(closes) < 10:
        return []
    diffs = np.diff(closes[-10:])
    up = int(np.sum(diffs > 0))
    dn = int(np.sum(diffs < 0))
    patterns: list[str] = []
    if up >= 7:
        patterns.append("strong_uptrend")
    elif up >= 5:
        patterns.append("mild_uptrend")
    if dn >= 7:
        patterns.append("strong_downtrend")
    elif dn >= 5:
        patterns.append("mild_downtrend")
    return patterns


def _detect_double_patterns(closes: np.ndarray) -> list[str]:
    """더블 탑/바텀을 간이 탐지한다."""
    last_20 = closes[-20:] if len(closes) >= 20 else closes
    patterns: list[str] = []
    lows_arr = _find_local_lows(last_20, 2)
    highs_arr = _find_local_highs(last_20, 2)
    if len(lows_arr) >= 2 and abs(lows_arr[-1] - lows_arr[-2]) / lows_arr[-2] < 0.02:
        patterns.append("double_bottom")
    if len(highs_arr) >= 2 and abs(highs_arr[-1] - highs_arr[-2]) / highs_arr[-2] < 0.02:
        patterns.append("double_top")
    return patterns


def _detect_patterns(closes: np.ndarray) -> list[str]:
    """최근 캔들 패턴을 식별한다."""
    return _detect_trend(closes) + _detect_double_patterns(closes)


class HistoryAnalyzer:
    """과거 가격 패턴을 분석하여 지지/저항 수준과 패턴을 반환한다."""

    def analyze(self, candles: list[OHLCV]) -> HistoryPattern:
        """캔들 데이터로부터 패턴, 지지/저항 수준을 분석한다."""
        if len(candles) < _MIN_CANDLES:
            logger.warning("분석에 필요한 캔들 수 부족: %d", len(candles))
            return HistoryPattern(patterns=[], support_levels=[], resistance_levels=[])
        closes = np.array([c.close for c in candles], dtype=float)
        highs = np.array([c.high for c in candles], dtype=float)
        lows = np.array([c.low for c in candles], dtype=float)
        resistance = _cluster_levels(_find_local_highs(highs, _PIVOT_WINDOW), _CLUSTER_PCT)
        support = _cluster_levels(_find_local_lows(lows, _PIVOT_WINDOW), _CLUSTER_PCT)
        patterns = _detect_patterns(closes)
        logger.debug("패턴 분석: patterns=%s, S=%d, R=%d", patterns, len(support), len(resistance))
        return HistoryPattern(patterns=patterns, support_levels=support, resistance_levels=resistance)
