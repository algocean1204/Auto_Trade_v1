"""F8 ML -- 21개 피처를 생성한다."""

from __future__ import annotations

import math

from src.common.logger import get_logger
from src.optimization.models import FeatureMatrix, PreparedData

logger = get_logger(__name__)

# 21개 피처 이름 목록이다
FEATURE_NAMES: list[str] = [
    "rsi", "macd", "bb_position", "atr", "ema20_50_ratio",
    "sma200_distance", "obi", "cvd", "vpin", "whale_score",
    "volume_ratio", "leader_momentum", "vix", "spread",
    "regime_score", "sector_score", "contango", "nav_premium",
    "leverage_decay", "fear_greed", "net_liquidity",
]

# 각 피처의 기본값이다 (결측 시 대체용)
_DEFAULTS: dict[str, float] = {name: 0.0 for name in FEATURE_NAMES}


def _extract_single_feature(row: dict, name: str) -> float:
    """단일 행에서 하나의 피처 값을 추출한다. NaN/inf이면 기본값을 반환한다."""
    val = row.get(name)
    if val is None:
        return _DEFAULTS[name]
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return _DEFAULTS[name]
        return result
    except (ValueError, TypeError):
        return _DEFAULTS[name]


def _compute_derived_features(row: dict) -> dict[str, float]:
    """원본 컬럼으로부터 파생 피처를 계산한다.

    DB에 직접 저장되지 않은 피처는 여기서 계산한다.
    """
    derived: dict[str, float] = {}

    # EMA 비율: ema_20 / ema_50 이다 (indicator_persister가 ema_20으로 저장한다)
    ema20 = _safe_float(row.get("ema_20"), 1.0)
    ema50 = _safe_float(row.get("ema_50"), 1.0)
    derived["ema20_50_ratio"] = ema20 / ema50 if ema50 != 0 else 1.0

    # SMA200 거리: (price - sma_200) / sma_200 이다 (indicator_persister가 sma_200으로 저장한다)
    price = _safe_float(row.get("price"), 0.0)
    sma200 = _safe_float(row.get("sma_200"), 1.0)
    derived["sma200_distance"] = (
        (price - sma200) / sma200 if sma200 != 0 else 0.0
    )

    # 볼린저 밴드 위치: (price - lower) / (upper - lower) 이다
    bb_upper = _safe_float(row.get("bb_upper"), 1.0)
    bb_lower = _safe_float(row.get("bb_lower"), 0.0)
    bb_range = bb_upper - bb_lower
    derived["bb_position"] = (
        (price - bb_lower) / bb_range if bb_range != 0 else 0.5
    )

    return derived


def _safe_float(val: float | str | None, default: float) -> float:
    """안전하게 float 변환한다. NaN/inf이면 기본값을 반환한다."""
    if val is None:
        return default
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def _build_feature_vector(row: dict) -> list[float]:
    """단일 행에서 21차원 피처 벡터를 생성한다."""
    derived = _compute_derived_features(row)
    merged = {**row, **derived}

    vector: list[float] = []
    for name in FEATURE_NAMES:
        vector.append(_extract_single_feature(merged, name))
    return vector


def engineer_features(prepared: PreparedData) -> FeatureMatrix:
    """정제된 데이터에서 21개 피처 행렬을 생성한다.

    각 행에서 RSI, MACD, BB, ATR, EMA, OBI, CVD, VPIN 등
    21개 피처를 추출/계산하여 FeatureMatrix로 반환한다.
    """
    features: list[list[float]] = []

    for row in prepared.data:
        vector = _build_feature_vector(row)
        features.append(vector)

    logger.info(
        "피처 엔지니어링 완료: %d행 x %d피처",
        len(features), len(FEATURE_NAMES),
    )

    return FeatureMatrix(
        features=features,
        feature_names=FEATURE_NAMES,
        row_count=len(features),
    )
