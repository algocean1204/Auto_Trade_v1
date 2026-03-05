"""FS 호가창 깊이 분석기 -- 호가창의 유동성 깊이를 분석한다.

매수/매도 호가 잔량 분포를 분석하여 유동성 점수와 불균형을 계산한다.
지지 가격대를 식별하여 스캘핑 진입 판단에 활용한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.scalping.models import DepthAnalysis

_logger = get_logger(__name__)

# 깊이 점수 가중치이다 (가까운 호가일수록 높은 가중치)
_LEVEL_WEIGHTS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]

# 지지선 판별 임계값이다 (평균 잔량 대비 배수)
_SUPPORT_MULTIPLIER = 2.0


def _extract_volumes(
    levels: list[dict],
) -> list[tuple[float, int]]:
    """호가 단계에서 (가격, 잔량) 쌍을 추출한다."""
    result: list[tuple[float, int]] = []
    for level in levels:
        price = float(level.get("price", 0))
        volume = int(level.get("volume", 0))
        if price > 0:
            result.append((price, volume))
    return result


def _weighted_volume(volumes: list[int]) -> float:
    """가중 잔량 합을 계산한다. 가까운 호가에 높은 가중치를 부여한다."""
    total = 0.0
    for i, vol in enumerate(volumes):
        weight = _LEVEL_WEIGHTS[i] if i < len(_LEVEL_WEIGHTS) else 0.1
        total += vol * weight
    return total


def _find_support_levels(
    bids: list[tuple[float, int]],
) -> list[float]:
    """매수 호가 중 잔량이 평균의 2배 이상인 가격대를 지지선으로 식별한다."""
    if not bids:
        return []
    volumes = [vol for _, vol in bids]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    threshold = avg_vol * _SUPPORT_MULTIPLIER
    supports: list[float] = []
    for price, vol in bids:
        if vol >= threshold:
            supports.append(price)
    return supports


def analyze_depth(orderbook: dict) -> DepthAnalysis:
    """호가창 데이터를 분석하여 깊이 점수, 불균형, 지지선을 반환한다.

    depth_score: 0~1 범위, 1에 가까울수록 유동성 풍부하다.
    imbalance: -1~+1 범위, 양수=매수 우세이다.
    """
    bids_raw = orderbook.get("bids", [])
    asks_raw = orderbook.get("asks", [])
    bids = _extract_volumes(bids_raw)
    asks = _extract_volumes(asks_raw)
    bid_vols = [vol for _, vol in bids]
    ask_vols = [vol for _, vol in asks]
    bid_weighted = _weighted_volume(bid_vols)
    ask_weighted = _weighted_volume(ask_vols)
    total_weighted = bid_weighted + ask_weighted
    # 깊이 점수: 총 가중 잔량을 정규화한다 (기준: 10000)
    depth_score = min(1.0, total_weighted / 10000.0)
    # 불균형: OBI와 동일 공식이다
    if total_weighted > 0:
        imbalance = (bid_weighted - ask_weighted) / total_weighted
    else:
        imbalance = 0.0
    imbalance = max(-1.0, min(1.0, imbalance))
    support_levels = _find_support_levels(bids)
    return DepthAnalysis(
        depth_score=round(depth_score, 4),
        imbalance=round(imbalance, 4),
        support_levels=support_levels,
    )
