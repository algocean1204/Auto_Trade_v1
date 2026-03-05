"""FW OBI 계산기 -- Order Book Imbalance를 계산한다.

OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume)
범위: -1.0(매도 우세) ~ +1.0(매수 우세)이다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.websocket.models import OBIValue, OrderbookSnapshot

_logger = get_logger(__name__)


def _sum_volume(levels: list[dict]) -> int:
    """호가 단계들의 총 잔량을 합산한다."""
    total = 0
    for level in levels:
        vol = level.get("volume", 0)
        if isinstance(vol, (int, float)):
            total += int(vol)
    return total


def _classify_direction(score: float) -> str:
    """OBI 점수를 방향 문자열로 분류한다."""
    if score > 0.3:
        return "strong_buy"
    if score > 0.1:
        return "buy"
    if score < -0.3:
        return "strong_sell"
    if score < -0.1:
        return "sell"
    return "neutral"


def calculate_obi(snapshot: OrderbookSnapshot) -> OBIValue:
    """호가창 스냅샷으로 OBI를 계산한다.

    bid/ask 잔량이 모두 0이면 score=0.0, neutral을 반환한다.
    """
    bid_vol = _sum_volume(snapshot.bids)
    ask_vol = _sum_volume(snapshot.asks)
    total = bid_vol + ask_vol
    if total == 0:
        return OBIValue(score=0.0, direction="neutral")
    score = (bid_vol - ask_vol) / total
    # -1.0 ~ 1.0 클램핑한다
    score = max(-1.0, min(1.0, score))
    direction = _classify_direction(score)
    return OBIValue(score=round(score, 4), direction=direction)
