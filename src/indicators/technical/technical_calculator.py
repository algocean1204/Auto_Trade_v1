"""F3 지표 -- RSI, MACD, 볼린저, ATR 등 기술적 지표 계산이다."""
from __future__ import annotations

import numpy as np

from src.common.broker_gateway import OHLCV
from src.common.logger import get_logger
from src.indicators.models import TechnicalIndicators

logger = get_logger(__name__)

_MIN_CANDLES: int = 50


# ── Atom 순수 함수 ──────────────────────────────────────────


def calc_ema(closes: np.ndarray, period: int) -> float:
    """지수이동평균(EMA)을 계산한다. 최종 값만 반환한다."""
    if len(closes) < period:
        return float(closes[-1])
    multiplier = 2.0 / (period + 1)
    ema = float(closes[0])
    for price in closes[1:]:
        ema = (float(price) - ema) * multiplier + ema
    return ema


def calc_sma(closes: np.ndarray, period: int) -> float:
    """단순이동평균(SMA)을 계산한다. 최종 값만 반환한다."""
    if len(closes) < period:
        return float(np.mean(closes))
    return float(np.mean(closes[-period:]))


def calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    """RSI(상대강도지수)를 계산한다. Wilder 평활법 사용한다."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float]:
    """MACD, Signal, Histogram을 계산한다."""
    fast_ema = _ema_series(closes, fast)
    slow_ema = _ema_series(closes, slow)
    macd_line = fast_ema - slow_ema
    signal_line = _ema_series(macd_line, signal)
    histogram = macd_line - signal_line
    return float(macd_line[-1]), float(signal_line[-1]), float(histogram[-1])


def calc_bollinger(
    closes: np.ndarray,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[float, float, float]:
    """볼린저 밴드 (upper, middle, lower)를 계산한다."""
    if len(closes) < period:
        mid = float(np.mean(closes))
        std = float(np.std(closes))
        return mid + std_dev * std, mid, mid - std_dev * std
    window = closes[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window))
    return mid + std_dev * std, mid, mid - std_dev * std


def calc_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """ATR(평균진폭)을 계산한다. Wilder 평활법 사용한다."""
    if len(closes) < 2:
        return float(highs[0] - lows[0]) if len(highs) > 0 else 0.0
    prev_close = closes[:-1]
    cur_high = highs[1:]
    cur_low = lows[1:]
    tr = np.maximum(
        cur_high - cur_low,
        np.maximum(np.abs(cur_high - prev_close), np.abs(cur_low - prev_close)),
    )
    if len(tr) < period:
        return float(np.mean(tr))
    atr_val = float(np.mean(tr[:period]))
    for i in range(period, len(tr)):
        atr_val = (atr_val * (period - 1) + float(tr[i])) / period
    return atr_val


# ── 내부 헬퍼 ────────────────────────────────────────────


def _ema_series(data: np.ndarray, period: int) -> np.ndarray:
    """EMA 시리즈 전체를 반환한다. MACD 계산용 내부 함수이다."""
    result = np.empty_like(data, dtype=float)
    multiplier = 2.0 / (period + 1)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = (float(data[i]) - result[i - 1]) * multiplier + result[i - 1]
    return result


def _extract_arrays(candles: list[OHLCV]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """캔들 리스트에서 종가/고가/저가 배열을 추출한다."""
    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    return closes, highs, lows


def _build_result(
    rsi: float, macd: float, macd_sig: float, macd_hist: float,
    bb_upper: float, bb_mid: float, bb_lower: float,
    atr: float, closes: np.ndarray,
) -> TechnicalIndicators:
    """계산된 지표 값들로 TechnicalIndicators를 조립한다."""
    return TechnicalIndicators(
        rsi=round(rsi, 2), macd=round(macd, 4), macd_signal=round(macd_sig, 4),
        macd_histogram=round(macd_hist, 4), bb_upper=round(bb_upper, 4),
        bb_middle=round(bb_mid, 4), bb_lower=round(bb_lower, 4), atr=round(atr, 4),
        ema_20=round(calc_ema(closes, 20), 4), ema_50=round(calc_ema(closes, 50), 4),
        sma_200=round(calc_sma(closes, 200), 4),
    )


# ── 오케스트레이터 ──────────────────────────────────────────


class TechnicalCalculator:
    """일봉 데이터로 기술적 지표를 종합 계산한다."""

    def calculate(self, candles: list[OHLCV]) -> TechnicalIndicators:
        """캔들 리스트로부터 전체 기술적 지표를 산출한다."""
        if len(candles) < _MIN_CANDLES:
            logger.warning("캔들 수 부족: %d < %d", len(candles), _MIN_CANDLES)
        closes, highs, lows = _extract_arrays(candles)
        rsi = calc_rsi(closes)
        macd, macd_sig, macd_hist = calc_macd(closes)
        bb_upper, bb_mid, bb_lower = calc_bollinger(closes)
        atr = calc_atr(highs, lows, closes)
        return _build_result(rsi, macd, macd_sig, macd_hist, bb_upper, bb_mid, bb_lower, atr, closes)
