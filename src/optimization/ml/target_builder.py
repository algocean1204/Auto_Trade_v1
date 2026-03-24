"""F8 ML -- P(+1%/5min) 타겟 라벨을 생성한다."""

from __future__ import annotations

import math

from src.common.logger import get_logger
from src.optimization.models import LabelVector, PreparedData

logger = get_logger(__name__)

# 5분 내 +1% 상승이 양성 라벨의 기준이다
_PROFIT_THRESHOLD: float = 0.01
_LOOKAHEAD_MINUTES: int = 5


def _safe_float(val: float | str | None, default: float = 0.0) -> float:
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


def _compute_forward_return(
    data: list[dict], idx: int,
) -> float | None:
    """현재 인덱스에서 5분 뒤 수익률을 계산한다.

    데이터가 분봉이라 가정하고, idx + _LOOKAHEAD_MINUTES 위치의
    가격 대비 수익률을 반환한다. 범위 초과 시 None이다.
    """
    future_idx = idx + _LOOKAHEAD_MINUTES
    if future_idx >= len(data):
        return None

    current_price = _safe_float(data[idx].get("price"))
    future_price = _safe_float(data[future_idx].get("price"))

    if current_price <= 0:
        return None

    return (future_price - current_price) / current_price


def _assign_label(forward_return: float | None) -> int:
    """수익률을 이진 라벨로 변환한다.

    +1% 이상이면 1 (양성), 그 외 0 (음성)이다.
    None이면 0으로 처리한다 (lookahead 부족).
    """
    if forward_return is None:
        return 0
    return 1 if forward_return >= _PROFIT_THRESHOLD else 0


def build_targets(prepared: PreparedData) -> LabelVector:
    """정제된 데이터에서 P(+1%/5min) 타겟 라벨을 생성한다.

    각 시점에서 5분 뒤 +1% 이상 상승 여부를 이진 라벨로 변환한다.
    positive_ratio로 클래스 불균형 정도를 함께 반환한다.
    """
    labels: list[int] = []

    for idx in range(len(prepared.data)):
        fwd_return = _compute_forward_return(prepared.data, idx)
        label = _assign_label(fwd_return)
        labels.append(label)

    positive_count = sum(labels)
    total = len(labels) if labels else 1
    ratio = positive_count / total

    logger.info(
        "타겟 생성 완료: %d개, 양성비율=%.2f%%",
        total, ratio * 100,
    )

    return LabelVector(labels=labels, positive_ratio=ratio)
