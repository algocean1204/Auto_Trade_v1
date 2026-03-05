"""FS 시장 충격 추정기 -- 주문이 시장에 미치는 충격을 추정한다.

주문 크기와 호가창 깊이를 기반으로 예상 슬리피지와 비용을 계산한다.
Kyle의 Lambda 모델을 간소화하여 적용한다.
"""
from __future__ import annotations

import math

from src.common.logger import get_logger
from src.scalping.models import DepthAnalysis, ImpactEstimate

_logger = get_logger(__name__)

# 충격 계수 상수이다
_BASE_IMPACT_COEFF = 0.1  # 기본 시장 충격 계수
_DEPTH_DAMPENING = 0.5     # 깊이가 높을수록 충격 감소 비율
_MAX_SLIPPAGE_PCT = 5.0    # 최대 슬리피지 상한 (%)


def _calculate_relative_size(
    order_size: int,
    depth_score: float,
) -> float:
    """주문 크기의 호가창 대비 상대적 크기를 계산한다.

    depth_score가 0이면 최대 충격, 1이면 최소 충격이다.
    """
    if depth_score <= 0:
        return float(order_size)
    # 깊이가 높을수록 상대적 크기가 줄어든다
    effective_depth = depth_score * 10000
    if effective_depth <= 0:
        return float(order_size)
    return order_size / effective_depth


def _square_root_impact(relative_size: float) -> float:
    """제곱근 모델로 시장 충격(%)을 추정한다.

    Kyle 모델 간소화: impact = coeff * sqrt(relative_size)이다.
    """
    if relative_size <= 0:
        return 0.0
    impact = _BASE_IMPACT_COEFF * math.sqrt(relative_size)
    return min(impact * 100.0, _MAX_SLIPPAGE_PCT)


def estimate_impact(
    order_size: int,
    depth: DepthAnalysis,
    price: float = 0.0,
) -> ImpactEstimate:
    """주문 크기와 깊이 분석으로 시장 충격을 추정한다.

    depth_score가 높으면(유동성 풍부) 충격이 작고,
    imbalance가 주문 방향과 반대면 충격이 증가한다.
    """
    if order_size <= 0:
        return ImpactEstimate(expected_slippage_pct=0.0, impact_cost=0.0)
    # 깊이 댐프닝 적용한다
    adjusted_depth = depth.depth_score * _DEPTH_DAMPENING
    relative = _calculate_relative_size(order_size, adjusted_depth)
    slippage_pct = _square_root_impact(relative)
    # 불균형 보정: 매도 우세(음수)일 때 매수 충격 증가한다
    if depth.imbalance < 0:
        slippage_pct *= (1.0 + abs(depth.imbalance) * 0.5)
    slippage_pct = min(slippage_pct, _MAX_SLIPPAGE_PCT)
    # 비용 = 가격 * 수량 * 슬리피지 비율이다
    impact_cost = price * order_size * (slippage_pct / 100.0) if price > 0 else 0.0
    return ImpactEstimate(
        expected_slippage_pct=round(slippage_pct, 4),
        impact_cost=round(impact_cost, 2),
    )
