"""
종목별 지표 히스토리 분석 모듈 (핵심 차별점)

기계적 지표 해석이 아닌, "이 종목에서 이 지표가 과거에 어떤 의미였는가?"를
분석하여 맥락적 시그널을 생성한다.

예시: NVDA RSI 75
- 일반적 해석: 과매수 -> 매도
- 맥락적 해석: NVDA는 RSI 70~85에서 평균 12일 체류,
  이 구간에서 1일 후 수익률 +0.8% -> 여전히 매수 가능
"""

from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

# RSI 과매수 기준값
_RSI_OVERBOUGHT: float = 70.0

# RSI 강한 과매수 기준값
_RSI_STRONG_OVERBOUGHT: float = 80.0

# RSI 과매도 기준값
_RSI_OVERSOLD: float = 30.0

# 백분위 상위 임계값 (이 이상이면 고위 백분위 구간)
_PERCENTILE_HIGH: float = 80.0

# 백분위 하위 임계값 (이 이하이면 저위 백분위 구간)
_PERCENTILE_LOW: float = 20.0


class TickerHistoryAnalyzer:
    """종목별 지표 히스토리 기반 맥락 분석기.

    과거 데이터를 기반으로 현재 지표 값의 의미를 종목 특성에 맞게 해석한다.
    """

    def analyze_indicator_history(
        self,
        ticker: str,
        indicator: str,
        current_value: float,
        price_history: pd.DataFrame,
        indicator_history: list[dict],
        lookback_days: int = 252,
    ) -> dict[str, Any]:
        """종목의 과거 지표 행동 패턴을 분석한다.

        Args:
            ticker: 종목 심볼.
            indicator: 지표 이름 (예: "rsi_14", "macd").
            current_value: 현재 지표 값.
            price_history: OHLCV DataFrame (forward return 계산용).
            indicator_history: 과거 지표 값 리스트.
                각 항목: {"value": float, "recorded_at": datetime, "metadata": dict}
            lookback_days: 분석 대상 과거 기간 (거래일 수).

        Returns:
            분석 결과 딕셔너리:
            {
                "ticker", "indicator", "current_value",
                "percentile": float,
                "historical_forward_returns": {"1d", "3d", "5d"},
                "avg_stay_days": float,
                "similar_period_count": int,
                "contextual_signal": {
                    "direction", "strength", "reason",
                    "override_traditional": bool
                }
            }
        """
        logger.info(
            "지표 히스토리 분석: ticker=%s, indicator=%s, value=%.2f",
            ticker, indicator, current_value,
        )

        # 히스토리 값 추출
        history_values = [h["value"] for h in indicator_history if h.get("value") is not None]

        # lookback_days로 히스토리 제한
        if len(history_values) > lookback_days:
            history_values = history_values[-lookback_days:]

        # 백분위 계산
        percentile = self._calculate_percentile(current_value, history_values)

        # 유사 기간 탐색
        tolerance = self._get_tolerance(indicator, current_value)
        similar_periods = self._find_similar_periods(
            indicator_history, current_value, tolerance
        )
        similar_count = len(similar_periods)

        # 선행 수익률 계산
        fwd_returns = {
            "1d": self._avg_forward_return(similar_periods, price_history, 1),
            "3d": self._avg_forward_return(similar_periods, price_history, 3),
            "5d": self._avg_forward_return(similar_periods, price_history, 5),
        }

        # 구간 체류 일수
        band_width = self._get_band_width(indicator, current_value)
        avg_stay = self._avg_stay_duration(
            indicator_history, current_value, band_width
        )

        # 맥락적 신호 생성
        if indicator in ("rsi_7", "rsi_14", "rsi_21"):
            contextual_signal = self._rsi_contextual_signal(
                current_value, percentile, fwd_returns, avg_stay
            )
        else:
            contextual_signal = self._generic_contextual_signal(
                indicator, current_value, percentile, fwd_returns
            )

        result = {
            "ticker": ticker,
            "indicator": indicator,
            "current_value": current_value,
            "percentile": round(percentile, 2),
            "historical_forward_returns": {
                k: round(v, 4) for k, v in fwd_returns.items()
            },
            "avg_stay_days": round(avg_stay, 1),
            "similar_period_count": similar_count,
            "contextual_signal": contextual_signal,
        }

        logger.info(
            "분석 완료: ticker=%s, indicator=%s, direction=%s, strength=%s",
            ticker, indicator,
            contextual_signal["direction"],
            contextual_signal["strength"],
        )
        return result

    def _calculate_percentile(self, value: float, history: list[float]) -> float:
        """현재값의 히스토리 내 백분위를 계산한다.

        Args:
            value: 현재 지표 값.
            history: 과거 지표 값 리스트.

        Returns:
            0~100 범위의 백분위. 히스토리가 비어 있으면 50.0.
        """
        if not history:
            return 50.0

        arr = np.array(history)
        count_below = np.sum(arr < value)
        return float(count_below / len(arr) * 100)

    def _find_similar_periods(
        self,
        history: list[dict],
        value: float,
        tolerance: float = 5.0,
    ) -> list[dict]:
        """과거에서 현재와 유사한 지표 값을 가진 기간을 찾는다.

        Args:
            history: 과거 지표 기록 리스트.
            value: 현재 지표 값.
            tolerance: 허용 오차 (절대값 기준).

        Returns:
            유사 기간의 리스트. 각 항목에 recorded_at 포함.
        """
        similar = []
        for record in history:
            rec_value = record.get("value")
            if rec_value is not None and abs(rec_value - value) <= tolerance:
                similar.append(record)
        return similar

    def _avg_forward_return(
        self,
        periods: list[dict],
        price_history: pd.DataFrame,
        days: int,
    ) -> float:
        """유사 기간 이후 평균 수익률을 계산한다.

        Args:
            periods: 유사 기간 리스트 (recorded_at 포함).
            price_history: OHLCV DataFrame.
            days: 선행 수익률 산출 기간 (거래일).

        Returns:
            평균 수익률 (비율). 유사 기간이 없으면 0.0.
        """
        if not periods or price_history.empty:
            return 0.0

        returns = []
        price_index = price_history.index

        for period in periods:
            recorded_at = period.get("recorded_at")
            if recorded_at is None:
                continue

            # recorded_at 시점을 price_history 인덱스에서 찾기
            # timezone-aware 비교를 위해 tz-naive로 변환
            if hasattr(recorded_at, "tzinfo") and recorded_at.tzinfo is not None:
                recorded_date = recorded_at.replace(tzinfo=None)
            else:
                recorded_date = recorded_at

            # 해당 날짜 이후의 인덱스를 찾기
            try:
                # tz-naive 인덱스로 변환하여 비교
                naive_index = price_index.tz_localize(None) if price_index.tz else price_index
                mask = naive_index >= pd.Timestamp(recorded_date)
                future_prices = price_history.loc[price_index[mask]]

                if len(future_prices) > days:
                    entry_price = float(future_prices["Close"].iloc[0])
                    exit_price = float(future_prices["Close"].iloc[days])
                    if entry_price > 0:
                        ret = (exit_price - entry_price) / entry_price
                        returns.append(ret)
            except (KeyError, IndexError, TypeError):
                continue

        if not returns:
            return 0.0

        return float(np.mean(returns))

    def _avg_stay_duration(
        self,
        history: list[dict],
        value: float,
        band_width: float = 5.0,
    ) -> float:
        """해당 구간에서의 평균 체류 일수를 계산한다.

        Args:
            history: 시간순 정렬된 과거 지표 기록 리스트.
            value: 현재 지표 값.
            band_width: 구간 폭 (value +/- band_width).

        Returns:
            평균 체류 거래일 수.
        """
        if not history:
            return 0.0

        lower_bound = value - band_width
        upper_bound = value + band_width

        stays: list[int] = []
        current_stay = 0

        for record in history:
            rec_value = record.get("value")
            if rec_value is not None and lower_bound <= rec_value <= upper_bound:
                current_stay += 1
            else:
                if current_stay > 0:
                    stays.append(current_stay)
                current_stay = 0

        # 마지막 체류 기간도 추가
        if current_stay > 0:
            stays.append(current_stay)

        if not stays:
            return 0.0

        return float(np.mean(stays))

    def _rsi_contextual_signal(
        self,
        value: float,
        percentile: float,
        fwd_returns: dict[str, float],
        stay_days: float,
    ) -> dict[str, Any]:
        """RSI 맥락적 판단을 수행한다.

        Thinking.md Addendum 2.3 기준:
        - RSI >= 70이지만 fwd_returns > 0.3%이고 stay_days > 5이면
          -> bullish_despite_overbought
        - RSI <= 30이지만 stay_days >= 3이면
          -> bearish_despite_oversold
        """
        avg_fwd_1d = fwd_returns.get("1d", 0.0)
        avg_fwd_3d = fwd_returns.get("3d", 0.0)

        # 과매수 구간 (RSI >= 70)
        if value >= _RSI_OVERBOUGHT:
            if avg_fwd_1d > 0.003 and stay_days > 5:
                return {
                    "direction": "bullish_despite_overbought",
                    "strength": "strong" if avg_fwd_1d > 0.006 else "moderate",
                    "reason": (
                        f"RSI {value:.1f}은 과매수이나, 이 종목에서 이 구간의 "
                        f"1일 후 평균 수익률이 {avg_fwd_1d * 100:.2f}%이고 "
                        f"평균 {stay_days:.1f}일 체류함. 상승 모멘텀 지속 가능성."
                    ),
                    "override_traditional": True,
                }
            elif avg_fwd_1d > 0.001:
                return {
                    "direction": "neutral",
                    "strength": "weak",
                    "reason": (
                        f"RSI {value:.1f}은 과매수이나, 선행 수익률이 소폭 양수 "
                        f"({avg_fwd_1d * 100:.2f}%). 관망 권장."
                    ),
                    "override_traditional": False,
                }
            else:
                return {
                    "direction": "bearish",
                    "strength": "strong" if value >= _RSI_STRONG_OVERBOUGHT else "moderate",
                    "reason": (
                        f"RSI {value:.1f}은 과매수이며, 이 종목에서도 이 구간 후 "
                        f"하락 경향 (1일 후 {avg_fwd_1d * 100:.2f}%)."
                    ),
                    "override_traditional": False,
                }

        # 과매도 구간 (RSI <= 30)
        if value <= _RSI_OVERSOLD:
            if stay_days >= 3 and avg_fwd_3d < -0.002:
                return {
                    "direction": "bearish_despite_oversold",
                    "strength": "strong" if stay_days >= 5 else "moderate",
                    "reason": (
                        f"RSI {value:.1f}은 과매도이나, 이 종목은 이 구간에서 "
                        f"평균 {stay_days:.1f}일 체류하며 3일 후 수익률 "
                        f"{avg_fwd_3d * 100:.2f}%로 추가 하락 가능성."
                    ),
                    "override_traditional": True,
                }
            elif avg_fwd_1d > 0.003:
                return {
                    "direction": "bullish",
                    "strength": "strong" if avg_fwd_1d > 0.006 else "moderate",
                    "reason": (
                        f"RSI {value:.1f}은 과매도이며, 이 종목에서 반등 경향 확인 "
                        f"(1일 후 {avg_fwd_1d * 100:.2f}%)."
                    ),
                    "override_traditional": False,
                }
            else:
                return {
                    "direction": "neutral",
                    "strength": "weak",
                    "reason": (
                        f"RSI {value:.1f}은 과매도이나, 반등 신호 약함. "
                        f"추가 데이터 확인 필요."
                    ),
                    "override_traditional": False,
                }

        # 중립 구간 (30 < RSI < 70)
        if value >= 55:
            direction = "bullish"
        elif value <= 45:
            direction = "bearish"
        else:
            direction = "neutral"

        # 선행 수익률로 보정
        if avg_fwd_1d > 0.003:
            direction = "bullish"
        elif avg_fwd_1d < -0.003:
            direction = "bearish"

        strength = "weak"
        if abs(avg_fwd_1d) > 0.006:
            strength = "strong"
        elif abs(avg_fwd_1d) > 0.002:
            strength = "moderate"

        return {
            "direction": direction,
            "strength": strength,
            "reason": (
                f"RSI {value:.1f}은 중립 구간. "
                f"이 종목 기준 백분위 {percentile:.0f}%, "
                f"1일 후 평균 수익률 {avg_fwd_1d * 100:.2f}%."
            ),
            "override_traditional": False,
        }

    def _generic_contextual_signal(
        self,
        indicator: str,
        value: float,
        percentile: float,
        fwd_returns: dict[str, float],
    ) -> dict[str, Any]:
        """일반 지표의 맥락적 판단을 수행한다.

        Args:
            indicator: 지표 이름.
            value: 현재 지표 값 (MACD는 histogram, Stochastic는 K 등).
            percentile: 해당 종목 내 백분위.
            fwd_returns: 선행 수익률.

        Returns:
            맥락적 신호 딕셔너리.
        """
        avg_fwd_1d = fwd_returns.get("1d", 0.0)

        # 선행 수익률 기반 방향 판단
        if avg_fwd_1d > 0.003:
            direction = "bullish"
        elif avg_fwd_1d < -0.003:
            direction = "bearish"
        else:
            direction = "neutral"

        # 백분위 기반 보정
        if percentile >= _PERCENTILE_HIGH and avg_fwd_1d < 0:
            direction = "bearish"
        elif percentile <= _PERCENTILE_LOW and avg_fwd_1d > 0:
            direction = "bullish"

        # 강도 판단
        if abs(avg_fwd_1d) > 0.006:
            strength = "strong"
        elif abs(avg_fwd_1d) > 0.002:
            strength = "moderate"
        else:
            strength = "weak"

        override = False
        # 전통적 해석과 맥락적 해석이 다른 경우
        if indicator == "stochastic":
            # Stochastic K > 80인데 bullish이면 override
            if value > 80 and direction == "bullish":
                override = True
            elif value < 20 and direction == "bearish":
                override = True
        elif indicator == "macd":
            # MACD histogram 부호와 방향이 다르면 override
            if value > 0 and direction == "bearish":
                override = True
            elif value < 0 and direction == "bullish":
                override = True

        return {
            "direction": direction,
            "strength": strength,
            "reason": (
                f"{indicator} 현재값 {value:.4f} (백분위 {percentile:.0f}%). "
                f"이 종목에서 유사 구간 후 1일 수익률 {avg_fwd_1d * 100:.2f}%."
            ),
            "override_traditional": override,
        }

    @staticmethod
    def _get_tolerance(indicator: str, value: float) -> float:
        """지표별 유사 구간 탐색 허용 오차를 반환한다."""
        tolerances = {
            "rsi_7": 5.0,
            "rsi_14": 5.0,
            "rsi_21": 5.0,
            "stochastic": 5.0,
            "adx": 5.0,
            "bollinger": 0.05,  # percent_b 기준
            "volume_ratio": 0.3,
        }
        if indicator in tolerances:
            return tolerances[indicator]
        # 값 기반 동적 허용 오차 (값의 10%)
        return max(abs(value) * 0.1, 0.01)

    @staticmethod
    def _get_band_width(indicator: str, value: float) -> float:
        """지표별 구간 체류 분석 밴드 폭을 반환한다."""
        band_widths = {
            "rsi_7": 5.0,
            "rsi_14": 5.0,
            "rsi_21": 5.0,
            "stochastic": 5.0,
            "adx": 5.0,
            "bollinger": 0.05,
            "volume_ratio": 0.3,
        }
        if indicator in band_widths:
            return band_widths[indicator]
        return max(abs(value) * 0.1, 0.01)
