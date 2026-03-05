"""FW VPIN 계산기 -- Volume-Synchronized PIN을 계산한다.

BVC(Bulk Volume Classification) 기반 VPIN이다.
거래를 bucket_size 단위로 그룹화하여 독성 주문 흐름을 측정한다.
"""
from __future__ import annotations

import math

from src.common.logger import get_logger
from src.websocket.models import TradeEvent, VPINValue

_logger = get_logger(__name__)

# VPIN 독성 수준 임계값이다
_THRESHOLD_LOW = 0.3
_THRESHOLD_MEDIUM = 0.6
_THRESHOLD_HIGH = 0.85
_DEFAULT_BUCKET_SIZE = 50
_MIN_BUCKETS = 5


def _classify_toxicity(score: float) -> str:
    """VPIN 점수를 독성 수준으로 분류한다."""
    if score >= _THRESHOLD_HIGH:
        return "extreme"
    if score >= _THRESHOLD_MEDIUM:
        return "high"
    if score >= _THRESHOLD_LOW:
        return "medium"
    return "low"


def _compute_bvc(trades: list[TradeEvent]) -> list[float]:
    """BVC(Bulk Volume Classification)로 각 체결의 매수 확률을 추정한다.

    가격 변화 기반 정규 CDF 근사(로지스틱)를 사용한다.
    """
    if len(trades) < 2:
        return [0.5] * len(trades)
    # 수익률 표준편차를 구한다
    returns: list[float] = []
    for i in range(1, len(trades)):
        prev = trades[i - 1].price
        curr = trades[i].price
        if prev > 0:
            returns.append((curr - prev) / prev)
    sigma = _std_dev(returns) if returns else 0.01
    if sigma < 1e-8:
        sigma = 0.01
    # 로지스틱 근사로 매수 확률 계산한다
    probabilities = [0.5]
    for i in range(1, len(trades)):
        prev = trades[i - 1].price
        curr = trades[i].price
        delta = (curr - prev) / prev if prev > 0 else 0.0
        z = delta / sigma
        prob = 1.0 / (1.0 + math.exp(-z))
        probabilities.append(prob)
    return probabilities


def _std_dev(values: list[float]) -> float:
    """표준편차를 계산한다."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def calculate_vpin(
    trades: list[TradeEvent],
    bucket_size: int = _DEFAULT_BUCKET_SIZE,
) -> VPINValue:
    """체결 목록에서 VPIN을 계산한다.

    bucket_size 단위로 거래량을 그룹화하여 매수/매도 불균형을 측정한다.
    데이터가 부족하면 score=0.0, low를 반환한다.
    """
    if len(trades) < _MIN_BUCKETS:
        return VPINValue(score=0.0, toxicity="low")
    probabilities = _compute_bvc(trades)
    # 버킷별 매수/매도 분류한다
    buy_volumes: list[float] = []
    sell_volumes: list[float] = []
    bucket_buy = 0.0
    bucket_sell = 0.0
    bucket_total = 0
    for i, trade in enumerate(trades):
        prob = probabilities[i]
        vol = trade.volume
        bucket_buy += prob * vol
        bucket_sell += (1.0 - prob) * vol
        bucket_total += vol
        if bucket_total >= bucket_size:
            buy_volumes.append(bucket_buy)
            sell_volumes.append(bucket_sell)
            bucket_buy, bucket_sell, bucket_total = 0.0, 0.0, 0
    if len(buy_volumes) < 2:
        return VPINValue(score=0.0, toxicity="low")
    # VPIN = 버킷 |매수-매도| 평균 / 버킷 총량 평균이다
    imbalances = [abs(b - s) for b, s in zip(buy_volumes, sell_volumes)]
    totals = [b + s for b, s in zip(buy_volumes, sell_volumes)]
    avg_imbalance = sum(imbalances) / len(imbalances)
    avg_total = sum(totals) / len(totals)
    if avg_total < 1e-8:
        return VPINValue(score=0.0, toxicity="low")
    score = avg_imbalance / avg_total
    score = max(0.0, min(1.0, score))
    toxicity = _classify_toxicity(score)
    return VPINValue(score=round(score, 4), toxicity=toxicity)
