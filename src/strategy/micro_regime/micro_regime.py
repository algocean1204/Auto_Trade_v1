"""F4 미시 레짐 -- HMM + 통계 하이브리드로 미시 시장 레짐을 분류한다.

HMM(은닉 마르코프 모델)으로 5분봉 수익률+변동성 시퀀스를 분석하여
'추세장(trending)' / '평균회귀(mean_reverting)' / '변동성(volatile)' / '정적(quiet)'을
확률적으로 판별한다. HMM 미가용 시 기존 통계 기반 폴백을 사용한다.
"""
from __future__ import annotations

import math

from src.common.logger import get_logger
from src.indicators.models import Candle5m
from src.strategy.models import MicroRegimeResult

logger = get_logger(__name__)

# HMM 상태 수 (trending, mean_reverting, volatile, quiet)
_N_STATES = 4
_STATE_LABELS = ["trending", "mean_reverting", "volatile", "quiet"]

# 통계 기반 폴백 가중치
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
_MIN_HMM_CANDLES = 30  # HMM은 30봉 이상 필요하다

# HMM 사용 가능 여부 (hmmlearn 패키지 의존)
_HMM_AVAILABLE = False
try:
    import numpy as np
    from hmmlearn.hmm import GaussianHMM
    _HMM_AVAILABLE = True
except ImportError:
    pass


def _extract_features(candles: list[Candle5m]) -> list[tuple[float, float]]:
    """5분봉에서 (수익률, 변동성) 특징 벡터를 추출한다."""
    features: list[tuple[float, float]] = []
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].close
        if prev_close <= 0:
            continue
        ret = candles[i].close / prev_close - 1
        # 캔들 내 변동성: (고가-저가)/종가
        volatility = (candles[i].high - candles[i].low) / candles[i].close if candles[i].close > 0 else 0.0
        features.append((ret, volatility))
    return features


def _hmm_classify(candles: list[Candle5m]) -> MicroRegimeResult | None:
    """HMM으로 미시 레짐을 판별한다. 패키지 미설치 또는 데이터 부족 시 None을 반환한다."""
    if not _HMM_AVAILABLE or len(candles) < _MIN_HMM_CANDLES:
        return None

    features = _extract_features(candles)
    if len(features) < _MIN_HMM_CANDLES - 1:
        return None

    try:
        X = np.array(features)
        model = GaussianHMM(
            n_components=_N_STATES,
            covariance_type="diag",
            n_iter=50,
            random_state=42,
        )
        model.fit(X)
        # 현재 상태 예측: 마지막 10봉의 상태를 예측한다
        states = model.predict(X)
        current_state = int(states[-1])

        # 상태별 특성으로 레이블을 매핑한다
        # 각 상태의 평균 수익률과 변동성으로 레짐을 결정한다
        means = model.means_  # (n_states, 2) -- [수익률, 변동성]
        state_labels = _assign_state_labels(means)
        regime = state_labels[current_state]

        # 확신도: 해당 상태의 사후 확률
        posteriors = model.predict_proba(X)
        confidence = float(posteriors[-1][current_state])

        logger.info(
            "HMM 미시 레짐: %s (state=%d, confidence=%.4f, states=%s)",
            regime, current_state, confidence, state_labels,
        )
        return MicroRegimeResult(
            regime=regime,
            score=round(confidence, 4),
            weights={"hmm_state": current_state, "hmm_confidence": confidence},
        )
    except Exception as exc:
        logger.debug("HMM 분류 실패 (통계 폴백): %s", exc)
        return None


def _assign_state_labels(means: np.ndarray) -> list[str]:
    """HMM 상태별 평균 특성으로 레짐 레이블을 할당한다.

    고변동성(vol > 0.005)을 최우선으로 판단한다 — 방향성과 무관하게 위험하다.
    수익률 절대값이 크고 변동성 낮으면 trending,
    수익률 작고 변동성 낮으면 quiet,
    나머지 mean_reverting.
    """
    labels: list[str] = []
    for idx, state_mean in enumerate(means):
        abs_ret = abs(float(state_mean[0]))
        vol = float(state_mean[1])
        if vol > 0.005:  # 고변동성 우선 판단
            label = "volatile"
        elif abs_ret > 0.001 and vol < 0.005:
            label = "trending"
        elif abs_ret < 0.0003 and vol < 0.003:
            label = "quiet"
        else:
            label = "mean_reverting"
        labels.append(label)
        logger.debug("HMM state %d: ret=%.5f vol=%.5f → %s", idx, abs_ret, vol, label)
    return labels


# === 통계 기반 폴백 함수 ===

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
    return round(min(annualized, 1.0), 4)


def _classify_regime(score: float) -> str:
    """합성 점수로 레짐을 분류한다.

    점수가 높을수록 방향성+활동성이 크다:
    trending(0.6+) > volatile(0.4~0.6) > mean_reverting(0.2~0.4) > quiet(0.2-)
    """
    if score >= _TRENDING_THRESHOLD:
        return "trending"
    if score >= _VOLATILE_THRESHOLD:
        return "volatile"
    if score >= _QUIET_THRESHOLD:
        return "mean_reverting"
    return "quiet"


def _stat_fallback(candles: list[Candle5m]) -> MicroRegimeResult:
    """통계 기반 폴백 분류이다. HMM 미가용 시 사용한다."""
    er = _efficiency_ratio(candles)
    ds = _directional_strength(candles)
    ac = _autocorrelation(candles)
    vol = _volatility_score(candles)

    weights = {"er": er, "ds": ds, "ac": ac, "vol": vol}
    score = round(
        _W_ER * er + _W_DS * ds + _W_AC * max(ac, 0) + _W_VOL * vol,
        4,
    )
    regime = _classify_regime(score)
    logger.debug(
        "미시 레짐(통계): %s score=%.4f (ER=%.4f DS=%.4f AC=%.4f VOL=%.4f)",
        regime, score, er, ds, ac, vol,
    )
    return MicroRegimeResult(regime=regime, score=score, weights=weights)


class MicroRegime:
    """HMM + 통계 하이브리드 미시 레짐 분류기이다.

    HMM(hmmlearn)이 설치되어 있고 캔들이 30개 이상이면 HMM으로 분류하고,
    그렇지 않으면 통계 기반(ER/DS/AC/VOL) 폴백을 사용한다.
    """

    def evaluate(self, candles_5m: list[Candle5m]) -> MicroRegimeResult:
        """5분봉 데이터로 미시 레짐을 분류한다."""
        if len(candles_5m) < _MIN_CANDLES:
            return MicroRegimeResult(regime="quiet", score=0.0)

        # HMM 우선 시도 → 실패 시 통계 폴백
        hmm_result = _hmm_classify(candles_5m)
        if hmm_result is not None:
            return hmm_result

        return _stat_fallback(candles_5m)
