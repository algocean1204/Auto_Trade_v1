"""
지표 종합 신호 생성 모듈 (Addendum 2.4)

모든 기술적 지표를 종합하여 단일 composite_score와 방향 신호를 생성한다.

composite_score: -1.0 ~ +1.0
direction: buy (> 0.2) / sell (< -0.2) / neutral
"""

from typing import Any

from src.indicators.calculator import TechnicalCalculator
from src.indicators.history_analyzer import TickerHistoryAnalyzer
from src.indicators.weights import WeightsManager
from src.utils.logger import get_logger

import pandas as pd

logger = get_logger(__name__)

# 맥락적 방향 -> 수치 매핑
_DIRECTION_SCORE_MAP: dict[str, float] = {
    "bullish": 1.0,
    "bullish_despite_overbought": 0.6,
    "neutral": 0.0,
    "bearish_despite_oversold": -0.6,
    "bearish": -1.0,
}

# 신호 강도 -> 배수 매핑
_STRENGTH_MULTIPLIER: dict[str, float] = {
    "strong": 1.0,
    "moderate": 0.7,
    "weak": 0.4,
}

# RSI 계열 지표: raw_value가 dict이며 "rsi" 필드를 스칼라로 사용한다.
_RSI_INDICATORS = frozenset({"rsi_7", "rsi_14", "rsi_21"})

# RSI 임계값 상수
_RSI_OVERBOUGHT: float = 70.0        # RSI 과매수 기준값
_RSI_STRONG_OVERBOUGHT: float = 80.0 # RSI 강한 과매수 기준값
_RSI_OVERSOLD: float = 30.0          # RSI 과매도 기준값
_RSI_MILD_BULL: float = 55.0         # RSI 완만한 상승 편향 기준값
_RSI_MILD_BEAR: float = 45.0         # RSI 완만한 하락 편향 기준값

# ADX 강한 추세 기준값 (이 이상이면 추세가 강하다고 판단)
_VOLUME_HIGH_THRESHOLD: float = 25.0


class IndicatorAggregator:
    """모든 기술적 지표를 종합하여 단일 신호를 생성하는 클래스.

    TechnicalCalculator로 지표를 계산하고,
    TickerHistoryAnalyzer로 종목별 맥락을 분석한 뒤,
    가중치를 적용하여 composite_score를 산출한다.
    """

    def __init__(
        self,
        calculator: TechnicalCalculator,
        history_analyzer: TickerHistoryAnalyzer,
        weights_manager: WeightsManager | None = None,
    ) -> None:
        self.calculator = calculator
        self.history_analyzer = history_analyzer
        self.weights_manager = weights_manager or WeightsManager()

    async def aggregate(
        self,
        ticker: str,
        price_df: pd.DataFrame,
        indicator_history: list[dict] | None = None,
        custom_weights: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """지표를 종합하여 단일 신호를 생성한다.

        1. 각 지표 계산 (calculator)
        2. 각 지표의 종목별 맥락 분석 (history_analyzer)
        3. 가중치 적용
        4. composite_score 계산

        Args:
            ticker: 종목 심볼.
            price_df: OHLCV DataFrame.
            indicator_history: 과거 지표 기록 리스트 (히스토리 분석용).
                None이면 맥락 분석을 건너뛰고 전통적 해석만 사용한다.
            custom_weights: 사용자 지정 가중치. None이면 저장된 가중치 사용.

        Returns:
            {
                "ticker": str,
                "composite_score": float,  # -1.0 ~ +1.0
                "direction": "buy" | "sell" | "neutral",
                "confidence": float,  # 0.0 ~ 1.0
                "signals": [...],
                "weights_used": dict,
            }
        """
        logger.info("지표 종합 분석 시작: ticker=%s", ticker)

        if price_df.empty or len(price_df) < 50:
            logger.warning("데이터 부족으로 분석 불가: ticker=%s, rows=%d", ticker, len(price_df))
            return self._empty_result(ticker)

        # 1. 가중치 로드
        if custom_weights is not None:
            weights = custom_weights
        else:
            weights = await self.weights_manager.get_weights()

        # 활성화 상태 확인
        enabled = await self.weights_manager.get_enabled()

        # 2. 전체 지표 계산
        raw_indicators = self.calculator.calculate_all(price_df)
        if not raw_indicators:
            return self._empty_result(ticker)

        # 3. 각 지표에 대해 맥락 분석 수행 및 신호 생성
        signals: list[dict] = []
        weighted_scores: list[float] = []
        total_weight: float = 0.0

        for indicator_name, info in TechnicalCalculator.INDICATORS.items():
            # 비활성화 또는 가중치 0인 지표는 건너뛰기
            weight = weights.get(indicator_name, 0)
            if not enabled.get(indicator_name, False) or weight <= 0:
                continue

            raw_value = raw_indicators.get(indicator_name)
            if raw_value is None:
                continue

            # 지표별로 맥락 분석에 사용할 단일 값 추출
            analysis_value = self._extract_scalar_value(indicator_name, raw_value)

            # 맥락 분석 (히스토리가 있는 경우만)
            contextual_signal: dict[str, Any] | None = None
            if indicator_history is not None:
                # 해당 지표의 히스토리만 필터링
                filtered_history = [
                    h for h in indicator_history
                    if h.get("indicator_name") == indicator_name
                ]

                if filtered_history:
                    analysis = self.history_analyzer.analyze_indicator_history(
                        ticker=ticker,
                        indicator=indicator_name,
                        current_value=analysis_value,
                        price_history=price_df,
                        indicator_history=filtered_history,
                    )
                    contextual_signal = analysis.get("contextual_signal")

            # 맥락 분석이 없으면 전통적 해석 사용
            if contextual_signal is None:
                contextual_signal = self._traditional_signal(
                    indicator_name, raw_value
                )

            # 방향 점수 계산
            direction_str = contextual_signal.get("direction", "neutral")
            strength_str = contextual_signal.get("strength", "weak")

            direction_score = _DIRECTION_SCORE_MAP.get(direction_str, 0.0)
            strength_mult = _STRENGTH_MULTIPLIER.get(strength_str, 0.4)
            weighted_score = direction_score * strength_mult * weight

            weighted_scores.append(weighted_score)
            total_weight += weight

            signals.append({
                "indicator": indicator_name,
                "category": info["category"],
                "raw_value": raw_value,
                "analysis_value": analysis_value,
                "contextual_signal": contextual_signal,
                "weight": weight,
                "contribution": round(weighted_score, 4),
            })

        # 4. composite_score 계산
        if total_weight > 0:
            composite_score = sum(weighted_scores) / total_weight
        else:
            composite_score = 0.0

        composite_score = max(-1.0, min(1.0, composite_score))

        # 방향 판단
        if composite_score > 0.2:
            direction = "buy"
        elif composite_score < -0.2:
            direction = "sell"
        else:
            direction = "neutral"

        # 신뢰도: 신호 일치도 기반
        confidence = self._calculate_confidence(signals, direction)

        result = {
            "ticker": ticker,
            "composite_score": round(composite_score, 4),
            "direction": direction,
            "confidence": round(confidence, 4),
            "signals": signals,
            "weights_used": weights,
        }

        logger.info(
            "지표 종합 완료: ticker=%s, score=%.4f, direction=%s, confidence=%.4f",
            ticker, composite_score, direction, confidence,
        )
        return result

    def _extract_scalar_value(
        self, indicator_name: str, raw_value: Any
    ) -> float:
        """지표의 원시 값에서 맥락 분석에 사용할 단일 스칼라 값을 추출한다."""
        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        if isinstance(raw_value, dict):
            # RSI 계열 (rsi_7, rsi_14, rsi_21): "rsi" 필드를 대표 값으로 사용한다.
            if indicator_name in _RSI_INDICATORS:
                return float(raw_value.get("rsi", 50.0))

            # 그 외 지표별 대표 값 매핑
            key_map = {
                "macd": "histogram",
                "stochastic": "k",
                "ma_cross": "ma_spread_pct",
                "bollinger": "percent_b",
            }
            key = key_map.get(indicator_name)
            if key and key in raw_value:
                return float(raw_value[key])
            # 첫 번째 숫자 값 반환
            for v in raw_value.values():
                if isinstance(v, (int, float)):
                    return float(v)

        return 0.0

    def _traditional_signal(
        self, indicator_name: str, raw_value: Any
    ) -> dict[str, Any]:
        """맥락 분석 없이 전통적 기술적 분석 해석을 수행한다."""

        # RSI 계열 공통 처리 (rsi_7, rsi_14, rsi_21 모두 동일 로직)
        if indicator_name in _RSI_INDICATORS:
            if isinstance(raw_value, dict):
                val = float(raw_value.get("rsi", 50.0))
                sig = float(raw_value.get("signal", 50.0))
                # RSI vs Signal 크로스 기반 판단
                if val >= _RSI_OVERBOUGHT:
                    direction = "bearish"
                    strength = "strong" if val >= _RSI_STRONG_OVERBOUGHT else "moderate"
                    reason = f"RSI {val:.1f} 과매수"
                elif val <= _RSI_OVERSOLD:
                    direction = "bullish"
                    strength = "moderate"
                    reason = f"RSI {val:.1f} 과매도"
                elif val > sig:
                    direction = "bullish"
                    strength = "moderate" if (val - sig) > 5 else "weak"
                    reason = f"RSI {val:.1f} > Signal {sig:.1f} 상승 기조"
                elif val < sig:
                    direction = "bearish"
                    strength = "moderate" if (sig - val) > 5 else "weak"
                    reason = f"RSI {val:.1f} < Signal {sig:.1f} 하락 기조"
                else:
                    direction = "neutral"
                    strength = "weak"
                    reason = f"RSI {val:.1f} Signal {sig:.1f} 중립"
            else:
                val = float(raw_value) if isinstance(raw_value, (int, float)) else 50.0
                if val >= _RSI_OVERBOUGHT:
                    direction, strength, reason = "bearish", "moderate", f"RSI {val:.1f} 과매수"
                elif val <= _RSI_OVERSOLD:
                    direction, strength, reason = "bullish", "moderate", f"RSI {val:.1f} 과매도"
                elif val >= _RSI_MILD_BULL:
                    direction, strength, reason = "bullish", "weak", f"RSI {val:.1f} 상승 편향"
                elif val <= _RSI_MILD_BEAR:
                    direction, strength, reason = "bearish", "weak", f"RSI {val:.1f} 하락 편향"
                else:
                    direction, strength, reason = "neutral", "weak", f"RSI {val:.1f} 중립"
            return {"direction": direction, "strength": strength, "reason": reason, "override_traditional": False}

        if indicator_name == "macd":
            hist = raw_value.get("histogram", 0.0) if isinstance(raw_value, dict) else 0.0
            macd_val = raw_value.get("macd", 0.0) if isinstance(raw_value, dict) else 0.0
            signal_val = raw_value.get("signal", 0.0) if isinstance(raw_value, dict) else 0.0
            if hist > 0 and macd_val > signal_val:
                strength = "strong" if hist > 0.5 else "moderate"
                return {"direction": "bullish", "strength": strength, "reason": f"MACD 히스토그램 양수 ({hist:.4f})", "override_traditional": False}
            elif hist < 0 and macd_val < signal_val:
                strength = "strong" if hist < -0.5 else "moderate"
                return {"direction": "bearish", "strength": strength, "reason": f"MACD 히스토그램 음수 ({hist:.4f})", "override_traditional": False}
            return {"direction": "neutral", "strength": "weak", "reason": "MACD 전환 구간", "override_traditional": False}

        if indicator_name == "stochastic":
            k = raw_value.get("k", 50.0) if isinstance(raw_value, dict) else 50.0
            d = raw_value.get("d", 50.0) if isinstance(raw_value, dict) else 50.0
            if k > 80:
                return {"direction": "bearish", "strength": "moderate", "reason": f"Stochastic K={k:.1f} 과매수", "override_traditional": False}
            elif k < 20:
                return {"direction": "bullish", "strength": "moderate", "reason": f"Stochastic K={k:.1f} 과매도", "override_traditional": False}
            elif k > d:
                return {"direction": "bullish", "strength": "weak", "reason": f"Stochastic K({k:.1f}) > D({d:.1f})", "override_traditional": False}
            else:
                return {"direction": "bearish", "strength": "weak", "reason": f"Stochastic K({k:.1f}) < D({d:.1f})", "override_traditional": False}

        if indicator_name == "ma_cross":
            if isinstance(raw_value, dict):
                cross_type = raw_value.get("cross_type", "none")
                above_20 = raw_value.get("price_above_20", False)
                above_50 = raw_value.get("price_above_50", False)
                if cross_type == "golden_cross":
                    return {"direction": "bullish", "strength": "strong", "reason": "골든크로스 발생", "override_traditional": False}
                elif cross_type == "dead_cross":
                    return {"direction": "bearish", "strength": "strong", "reason": "데드크로스 발생", "override_traditional": False}
                elif above_20 and above_50:
                    return {"direction": "bullish", "strength": "moderate", "reason": "가격이 MA20, MA50 위", "override_traditional": False}
                elif not above_20 and not above_50:
                    return {"direction": "bearish", "strength": "moderate", "reason": "가격이 MA20, MA50 아래", "override_traditional": False}
            return {"direction": "neutral", "strength": "weak", "reason": "MA 혼합 신호", "override_traditional": False}

        if indicator_name == "adx":
            val = float(raw_value) if isinstance(raw_value, (int, float)) else 0.0
            if val >= _VOLUME_HIGH_THRESHOLD:
                return {"direction": "neutral", "strength": "strong", "reason": f"ADX {val:.1f} 강한 추세", "override_traditional": False}
            return {"direction": "neutral", "strength": "weak", "reason": f"ADX {val:.1f} 약한 추세", "override_traditional": False}

        if indicator_name == "bollinger":
            if isinstance(raw_value, dict):
                pctb = raw_value.get("percent_b", 0.5)
                if pctb > 1.0:
                    return {"direction": "bearish", "strength": "moderate", "reason": f"%B={pctb:.2f} 상단 돌파", "override_traditional": False}
                elif pctb < 0.0:
                    return {"direction": "bullish", "strength": "moderate", "reason": f"%B={pctb:.2f} 하단 돌파", "override_traditional": False}
                elif pctb > 0.8:
                    return {"direction": "bearish", "strength": "weak", "reason": f"%B={pctb:.2f} 상단 근접", "override_traditional": False}
                elif pctb < 0.2:
                    return {"direction": "bullish", "strength": "weak", "reason": f"%B={pctb:.2f} 하단 근접", "override_traditional": False}
            return {"direction": "neutral", "strength": "weak", "reason": "볼린저 밴드 중립", "override_traditional": False}

        # 기본 중립 반환
        return {"direction": "neutral", "strength": "weak", "reason": f"{indicator_name} 분석 불가", "override_traditional": False}

    def _calculate_confidence(
        self, signals: list[dict], overall_direction: str
    ) -> float:
        """신호 일치도 기반 신뢰도를 계산한다.

        모든 신호가 같은 방향이면 높은 신뢰도,
        엇갈리면 낮은 신뢰도.

        Returns:
            0.0 ~ 1.0 범위의 신뢰도.
        """
        if not signals:
            return 0.0

        total_weight = sum(s["weight"] for s in signals)
        if total_weight == 0:
            return 0.0

        agreeing_weight = 0.0
        for signal in signals:
            sig_direction = signal["contextual_signal"].get("direction", "neutral")
            weight = signal["weight"]

            if overall_direction == "buy":
                if sig_direction in ("bullish", "bullish_despite_overbought"):
                    agreeing_weight += weight
            elif overall_direction == "sell":
                if sig_direction in ("bearish", "bearish_despite_oversold"):
                    agreeing_weight += weight
            else:
                if sig_direction == "neutral":
                    agreeing_weight += weight

        return agreeing_weight / total_weight

    @staticmethod
    def _empty_result(ticker: str) -> dict[str, Any]:
        """데이터 부족 시 빈 결과를 반환한다."""
        return {
            "ticker": ticker,
            "composite_score": 0.0,
            "direction": "neutral",
            "confidence": 0.0,
            "signals": [],
            "weights_used": {},
        }
