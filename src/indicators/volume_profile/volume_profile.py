"""F3 지표 -- 볼륨 프로파일 (POC + Value Area 70%)이다."""
from __future__ import annotations

import numpy as np

from src.common.broker_gateway import OHLCV
from src.common.logger import get_logger
from src.indicators.models import VolumeProfileResult

logger = get_logger(__name__)

_VALUE_AREA_PCT: float = 0.70
_NUM_BINS: int = 50
_PROXIMITY_PCT: float = 0.01  # 현재가 대비 1% 이내를 근접으로 판단한다


def _build_profile(candles: list[OHLCV], num_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """가격 구간별 거래량 히스토그램을 생성한다."""
    lows = np.array([c.low for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    volumes = np.array([c.volume for c in candles], dtype=float)
    price_min = float(np.min(lows))
    price_max = float(np.max(highs))
    if price_max <= price_min:
        price_max = price_min + 0.01
    edges = np.linspace(price_min, price_max, num_bins + 1)
    profile = np.zeros(num_bins, dtype=float)
    for i in range(len(candles)):
        typical = (candles[i].high + candles[i].low + candles[i].close) / 3.0
        idx = int((typical - price_min) / (price_max - price_min) * (num_bins - 1))
        idx = max(0, min(num_bins - 1, idx))
        profile[idx] += volumes[i]
    centers = (edges[:-1] + edges[1:]) / 2.0
    return centers, profile


def _find_poc(centers: np.ndarray, profile: np.ndarray) -> float:
    """POC(Point of Control)를 찾는다. 거래량이 최대인 가격이다."""
    poc_idx = int(np.argmax(profile))
    return float(centers[poc_idx])


def _find_value_area(
    centers: np.ndarray, profile: np.ndarray, pct: float,
) -> tuple[float, float]:
    """Value Area(70% 거래량 구간)의 상한/하한을 계산한다."""
    total = float(np.sum(profile))
    if total == 0:
        return float(centers[0]), float(centers[-1])
    poc_idx = int(np.argmax(profile))
    target = total * pct
    accumulated = float(profile[poc_idx])
    lo, hi = poc_idx, poc_idx
    while accumulated < target and (lo > 0 or hi < len(profile) - 1):
        expand_up = float(profile[hi + 1]) if hi + 1 < len(profile) else 0.0
        expand_dn = float(profile[lo - 1]) if lo - 1 >= 0 else 0.0
        if expand_up >= expand_dn and hi + 1 < len(profile):
            hi += 1
            accumulated += expand_up
        elif lo - 1 >= 0:
            lo -= 1
            accumulated += expand_dn
        else:
            hi = min(hi + 1, len(profile) - 1)
            accumulated += expand_up
    return float(centers[lo]), float(centers[hi])


def _detect_signals(
    current_price: float, poc: float, va_high: float, va_low: float,
) -> list[str]:
    """볼륨 프로파일 기반 신호를 생성한다."""
    signals: list[str] = []
    if poc > 0 and abs(current_price - poc) / poc < _PROXIMITY_PCT:
        signals.append("near_poc")
    if current_price > va_high:
        signals.append("above_value_area")
    elif current_price < va_low:
        signals.append("below_value_area")
    else:
        signals.append("inside_value_area")
    return signals


class VolumeProfile:
    """캔들 데이터로 POC와 Value Area를 계산한다."""

    def calculate(self, candles: list[OHLCV], current_price: float) -> VolumeProfileResult:
        """볼륨 프로파일(POC, Value Area)을 산출한다."""
        if not candles:
            return self._empty_result(current_price)
        centers, profile = _build_profile(candles, _NUM_BINS)
        poc = _find_poc(centers, profile)
        va_low, va_high = _find_value_area(centers, profile, _VALUE_AREA_PCT)
        signals = _detect_signals(current_price, poc, va_high, va_low)
        logger.debug("볼륨 프로파일: POC=%.2f, VA=%.2f~%.2f", poc, va_low, va_high)
        return self._build_result(current_price, poc, va_low, va_high, signals)

    def _build_result(
        self, price: float, poc: float, va_low: float, va_high: float, signals: list[str],
    ) -> VolumeProfileResult:
        """VolumeProfileResult를 조립한다."""
        support = va_low if price > va_low else None
        resistance = va_high if price < va_high else None
        return VolumeProfileResult(
            poc_price=round(poc, 4), value_area_high=round(va_high, 4),
            value_area_low=round(va_low, 4), is_above_poc=price > poc,
            support_level=round(support, 4) if support else None,
            resistance_level=round(resistance, 4) if resistance else None, signals=signals,
        )

    def _empty_result(self, current_price: float) -> VolumeProfileResult:
        """캔들 없을 때 기본 결과를 반환한다."""
        return VolumeProfileResult(
            poc_price=current_price,
            value_area_high=current_price,
            value_area_low=current_price,
            is_above_poc=False,
        )
