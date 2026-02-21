"""
기술적 지표 계산 엔진

pandas-ta를 활용하여 모멘텀, 추세, 변동성, 거래량 지표를 계산한다.

지표 목록:
- 모멘텀: RSI(7), RSI(14), RSI(21) + Signal(9) 각각, MACD(12,26,9), Stochastic(14,3,3)
- 추세: MA Cross(20/50), ADX(14)
- 변동성: Bollinger Bands(20,2), ATR(14)
- 거래량: Volume Ratio, OBV
"""

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

# RSI 과매수 기준값
_RSI_OVERBOUGHT: float = 70.0

# RSI 과매도 기준값
_RSI_OVERSOLD: float = 30.0


class TechnicalCalculator:
    """기술적 지표 계산 엔진.

    모든 계산 메서드는 OHLCV DataFrame을 입력으로 받는다.
    DataFrame 컬럼: Open, High, Low, Close, Volume
    """

    INDICATORS: dict[str, dict] = {
        "rsi_7": {"category": "momentum", "default_weight": 10},
        "rsi_14": {"category": "momentum", "default_weight": 15},
        "rsi_21": {"category": "momentum", "default_weight": 10},
        "macd": {"category": "momentum", "default_weight": 20},
        "stochastic": {"category": "momentum", "default_weight": 10},
        "ma_cross": {"category": "trend", "default_weight": 20},
        "adx": {"category": "trend", "default_weight": 5},
        "bollinger": {"category": "volatility", "default_weight": 10},
        "atr": {"category": "volatility", "default_weight": 0},
        "volume_ratio": {"category": "volume", "default_weight": 0},
        "obv": {"category": "volume", "default_weight": 0},
    }

    def calculate_all(self, df: pd.DataFrame) -> dict:
        """모든 지표를 한 번에 계산한다.

        Args:
            df: OHLCV DataFrame.

        Returns:
            지표명을 키로, 계산 결과를 값으로 갖는 딕셔너리.
        """
        if df.empty or len(df) < 50:
            logger.warning(
                "데이터 부족: %d rows (최소 50 필요)", len(df)
            )
            return {}

        logger.info("전체 지표 계산 시작: rows=%d", len(df))

        results: dict = {}

        # 3중 RSI 계산 (rsi_7, rsi_14, rsi_21 각각)
        triple_rsi = self.calculate_triple_rsi(df)
        results["rsi_7"] = triple_rsi["rsi_7"]
        results["rsi_14"] = triple_rsi["rsi_14"]
        results["rsi_21"] = triple_rsi["rsi_21"]

        results["macd"] = self.calculate_macd(df)
        results["stochastic"] = self.calculate_stochastic(df)
        results["ma_cross"] = self.calculate_ma_cross(df)
        results["adx"] = self.calculate_adx(df)
        results["bollinger"] = self.calculate_bollinger(df)
        results["atr"] = self.calculate_atr(df)
        results["volume_ratio"] = self.calculate_volume_ratio(df)
        results["obv"] = self.calculate_obv(df)

        logger.info("전체 지표 계산 완료: %d개 지표", len(results))
        return results

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """RSI(Relative Strength Index)를 계산한다. 하위 호환성을 위해 유지한다.

        Args:
            df: OHLCV DataFrame.
            period: RSI 기간. 기본값 14.

        Returns:
            최신 RSI 값. 계산 불가 시 50.0 (중립).
        """
        result = self.calculate_rsi_with_signal(df, period=period, signal_period=9)
        return result["rsi"]

    def calculate_rsi_with_signal(
        self, df: pd.DataFrame, period: int = 14, signal_period: int = 9
    ) -> dict:
        """RSI와 Signal 라인을 계산한다.

        Args:
            df: OHLCV DataFrame.
            period: RSI 기간.
            signal_period: Signal 라인 기간 (SMA of RSI).

        Returns:
            {"rsi": float, "signal": float, "histogram": float,
             "rsi_series": list[float], "signal_series": list[float],
             "overbought": bool, "oversold": bool}
        """
        try:
            rsi_series = ta.rsi(df["Close"], length=period)
            if rsi_series is None or rsi_series.dropna().empty:
                logger.warning("RSI(%d) 계산 불가: 데이터 부족", period)
                return {
                    "rsi": 50.0, "signal": 50.0, "histogram": 0.0,
                    "rsi_series": [], "signal_series": [],
                    "overbought": False, "oversold": False,
                }

            # Signal line = SMA of RSI
            signal_series = rsi_series.rolling(window=signal_period).mean()

            rsi_val = float(rsi_series.dropna().iloc[-1])
            sig_clean = signal_series.dropna()
            sig_val = float(sig_clean.iloc[-1]) if not sig_clean.empty else rsi_val
            histogram = rsi_val - sig_val

            # 차트용 마지막 N개 값 (최대 100 포인트)
            n = min(100, len(rsi_series.dropna()))
            rsi_list = [round(v, 2) for v in rsi_series.dropna().tail(n).tolist()]
            sig_list = [round(v, 2) for v in signal_series.dropna().tail(n).tolist()]

            logger.debug("RSI(%d) = %.2f, Signal = %.2f", period, rsi_val, sig_val)

            return {
                "rsi": round(rsi_val, 2),
                "signal": round(sig_val, 2),
                "histogram": round(histogram, 2),
                "rsi_series": rsi_list,
                "signal_series": sig_list,
                "overbought": rsi_val >= _RSI_OVERBOUGHT,
                "oversold": rsi_val <= _RSI_OVERSOLD,
            }
        except Exception as exc:
            logger.error("RSI(%d) 계산 오류: %s", period, exc)
            return {
                "rsi": 50.0, "signal": 50.0, "histogram": 0.0,
                "rsi_series": [], "signal_series": [],
                "overbought": False, "oversold": False,
            }

    def calculate_triple_rsi(self, df: pd.DataFrame) -> dict:
        """3중 RSI 분석을 수행한다. RSI(7), RSI(14), RSI(21) 각각 Signal(9) 포함.

        Args:
            df: OHLCV DataFrame.

        Returns:
            {"rsi_7": {...}, "rsi_14": {...}, "rsi_21": {...},
             "consensus": "bullish"|"bearish"|"neutral",
             "divergence": bool}
        """
        rsi_7 = self.calculate_rsi_with_signal(df, period=7, signal_period=9)
        rsi_14 = self.calculate_rsi_with_signal(df, period=14, signal_period=9)
        rsi_21 = self.calculate_rsi_with_signal(df, period=21, signal_period=9)

        # Consensus: 3개 모두 같은 방향인지 확인
        bullish_count = sum(
            1 for r in [rsi_7, rsi_14, rsi_21] if r["rsi"] > r["signal"]
        )
        bearish_count = sum(
            1 for r in [rsi_7, rsi_14, rsi_21] if r["rsi"] < r["signal"]
        )

        if bullish_count == 3:
            consensus = "bullish"
        elif bearish_count == 3:
            consensus = "bearish"
        else:
            consensus = "neutral"

        # Divergence: 단기 vs 장기 방향 불일치
        divergence = (
            (rsi_7["rsi"] > 70 and rsi_21["rsi"] < 50) or
            (rsi_7["rsi"] < 30 and rsi_21["rsi"] > 50)
        )

        logger.debug(
            "Triple RSI: rsi7=%.2f, rsi14=%.2f, rsi21=%.2f, consensus=%s, divergence=%s",
            rsi_7["rsi"], rsi_14["rsi"], rsi_21["rsi"], consensus, divergence,
        )

        return {
            "rsi_7": rsi_7,
            "rsi_14": rsi_14,
            "rsi_21": rsi_21,
            "consensus": consensus,
            "divergence": divergence,
        }

    def calculate_macd(self, df: pd.DataFrame) -> dict:
        """MACD를 계산한다.

        파라미터: fast=12, slow=26, signal=9

        Returns:
            {"macd": float, "signal": float, "histogram": float}
        """
        macd_df = ta.macd(df["Close"], fast=12, slow=26, signal=9)
        if macd_df is None or macd_df.dropna().empty:
            logger.warning("MACD 계산 불가: 데이터 부족")
            return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

        last = macd_df.dropna().iloc[-1]
        # pandas-ta MACD 컬럼명: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        macd_col = [c for c in macd_df.columns if c.startswith("MACD_")]
        hist_col = [c for c in macd_df.columns if c.startswith("MACDh_")]
        signal_col = [c for c in macd_df.columns if c.startswith("MACDs_")]

        result = {
            "macd": round(float(last[macd_col[0]]), 4) if macd_col else 0.0,
            "signal": round(float(last[signal_col[0]]), 4) if signal_col else 0.0,
            "histogram": round(float(last[hist_col[0]]), 4) if hist_col else 0.0,
        }
        logger.debug("MACD = %s", result)
        return result

    def calculate_stochastic(self, df: pd.DataFrame) -> dict:
        """Stochastic Oscillator를 계산한다.

        파라미터: k=14, d=3, smooth_k=3

        Returns:
            {"k": float, "d": float}
        """
        stoch_df = ta.stoch(
            df["High"], df["Low"], df["Close"], k=14, d=3, smooth_k=3
        )
        if stoch_df is None or stoch_df.dropna().empty:
            logger.warning("Stochastic 계산 불가: 데이터 부족")
            return {"k": 50.0, "d": 50.0}

        last = stoch_df.dropna().iloc[-1]
        k_col = [c for c in stoch_df.columns if c.startswith("STOCHk_")]
        d_col = [c for c in stoch_df.columns if c.startswith("STOCHd_")]

        result = {
            "k": round(float(last[k_col[0]]), 2) if k_col else 50.0,
            "d": round(float(last[d_col[0]]), 2) if d_col else 50.0,
        }
        logger.debug("Stochastic = %s", result)
        return result

    def calculate_ma_cross(self, df: pd.DataFrame) -> dict:
        """이동평균 크로스를 분석한다.

        20일/50일 단순이동평균의 교차 상태를 판단한다.

        Returns:
            {
                "ma_20": float, "ma_50": float,
                "cross_type": "golden_cross" | "dead_cross" | "none",
                "price_above_20": bool, "price_above_50": bool,
                "ma_spread_pct": float  # (ma20 - ma50) / ma50 * 100
            }
        """
        ma_20 = ta.sma(df["Close"], length=20)
        ma_50 = ta.sma(df["Close"], length=50)
        if ma_20 is None or ma_50 is None:
            logger.warning("MA Cross 계산 불가: 데이터 부족")
            return {
                "ma_20": 0.0, "ma_50": 0.0, "cross_type": "none",
                "price_above_20": False, "price_above_50": False,
                "ma_spread_pct": 0.0,
            }

        ma_20_clean = ma_20.dropna()
        ma_50_clean = ma_50.dropna()
        if ma_20_clean.empty or ma_50_clean.empty:
            return {
                "ma_20": 0.0, "ma_50": 0.0, "cross_type": "none",
                "price_above_20": False, "price_above_50": False,
                "ma_spread_pct": 0.0,
            }

        current_ma20 = float(ma_20_clean.iloc[-1])
        current_ma50 = float(ma_50_clean.iloc[-1])
        current_price = float(df["Close"].iloc[-1])

        # 크로스 판단: 최근 5일 내 교차 발생 여부
        cross_type = "none"
        lookback = min(5, len(ma_20_clean) - 1, len(ma_50_clean) - 1)
        if lookback > 0:
            # 동일 인덱스에서 비교하기 위해 정렬
            recent_20 = ma_20.iloc[-lookback - 1:]
            recent_50 = ma_50.iloc[-lookback - 1:]
            aligned = pd.DataFrame({"ma20": recent_20, "ma50": recent_50}).dropna()
            if len(aligned) >= 2:
                prev_diff = aligned["ma20"].iloc[0] - aligned["ma50"].iloc[0]
                curr_diff = aligned["ma20"].iloc[-1] - aligned["ma50"].iloc[-1]
                if prev_diff <= 0 < curr_diff:
                    cross_type = "golden_cross"
                elif prev_diff >= 0 > curr_diff:
                    cross_type = "dead_cross"

        ma_spread = (
            (current_ma20 - current_ma50) / current_ma50 * 100
            if current_ma50 != 0
            else 0.0
        )

        result = {
            "ma_20": round(current_ma20, 2),
            "ma_50": round(current_ma50, 2),
            "cross_type": cross_type,
            "price_above_20": current_price > current_ma20,
            "price_above_50": current_price > current_ma50,
            "ma_spread_pct": round(ma_spread, 4),
        }
        logger.debug("MA Cross = %s", result)
        return result

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """ADX(Average Directional Index)를 계산한다.

        Args:
            df: OHLCV DataFrame.
            period: ADX 기간. 기본값 14.

        Returns:
            최신 ADX 값. 계산 불가 시 0.0.
        """
        adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=period)
        if adx_df is None or adx_df.dropna().empty:
            logger.warning("ADX 계산 불가: 데이터 부족")
            return 0.0

        adx_col = [c for c in adx_df.columns if c.startswith("ADX_")]
        if not adx_col:
            return 0.0

        value = float(adx_df[adx_col[0]].dropna().iloc[-1])
        logger.debug("ADX(%d) = %.2f", period, value)
        return round(value, 2)

    def calculate_bollinger(self, df: pd.DataFrame) -> dict:
        """볼린저 밴드를 계산한다.

        파라미터: length=20, std=2

        Returns:
            {
                "upper": float, "middle": float, "lower": float,
                "bandwidth": float, "percent_b": float
            }
        """
        bb_df = ta.bbands(df["Close"], length=20, std=2)
        if bb_df is None or bb_df.dropna().empty:
            logger.warning("Bollinger Bands 계산 불가: 데이터 부족")
            return {
                "upper": 0.0, "middle": 0.0, "lower": 0.0,
                "bandwidth": 0.0, "percent_b": 0.5,
            }

        last = bb_df.dropna().iloc[-1]
        lower_col = [c for c in bb_df.columns if c.startswith("BBL_")]
        mid_col = [c for c in bb_df.columns if c.startswith("BBM_")]
        upper_col = [c for c in bb_df.columns if c.startswith("BBU_")]
        bw_col = [c for c in bb_df.columns if c.startswith("BBB_")]
        pctb_col = [c for c in bb_df.columns if c.startswith("BBP_")]

        upper = float(last[upper_col[0]]) if upper_col else 0.0
        middle = float(last[mid_col[0]]) if mid_col else 0.0
        lower = float(last[lower_col[0]]) if lower_col else 0.0
        bandwidth = float(last[bw_col[0]]) if bw_col else 0.0
        percent_b = float(last[pctb_col[0]]) if pctb_col else 0.5

        result = {
            "upper": round(upper, 2),
            "middle": round(middle, 2),
            "lower": round(lower, 2),
            "bandwidth": round(bandwidth, 4),
            "percent_b": round(percent_b, 4),
        }
        logger.debug("Bollinger = %s", result)
        return result

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """ATR(Average True Range)을 계산한다.

        Args:
            df: OHLCV DataFrame.
            period: ATR 기간. 기본값 14.

        Returns:
            최신 ATR 값. 계산 불가 시 0.0.
        """
        atr_series = ta.atr(df["High"], df["Low"], df["Close"], length=period)
        if atr_series is None or atr_series.dropna().empty:
            logger.warning("ATR 계산 불가: 데이터 부족")
            return 0.0

        value = float(atr_series.dropna().iloc[-1])
        logger.debug("ATR(%d) = %.4f", period, value)
        return round(value, 4)

    def calculate_volume_ratio(self, df: pd.DataFrame, period: int = 20) -> float:
        """거래량 비율을 계산한다.

        현재 거래량 / 20일 평균 거래량

        Args:
            df: OHLCV DataFrame.
            period: 평균 산출 기간. 기본값 20.

        Returns:
            거래량 비율. 1.0이면 평균과 동일.
        """
        if "Volume" not in df.columns or len(df) < period:
            logger.warning("Volume Ratio 계산 불가: 데이터 부족")
            return 1.0

        avg_volume = df["Volume"].iloc[-period:].mean()
        if avg_volume == 0:
            return 1.0

        current_volume = float(df["Volume"].iloc[-1])
        ratio = current_volume / avg_volume
        logger.debug("Volume Ratio(%d) = %.2f", period, ratio)
        return round(ratio, 4)

    def calculate_obv(self, df: pd.DataFrame) -> float:
        """OBV(On Balance Volume)를 계산한다.

        Returns:
            최신 OBV 값. 계산 불가 시 0.0.
        """
        obv_series = ta.obv(df["Close"], df["Volume"])
        if obv_series is None or obv_series.dropna().empty:
            logger.warning("OBV 계산 불가: 데이터 부족")
            return 0.0

        value = float(obv_series.dropna().iloc[-1])
        logger.debug("OBV = %.0f", value)
        return round(value, 2)
