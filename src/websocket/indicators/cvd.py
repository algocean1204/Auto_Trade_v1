"""FW CVD 계산기 -- Cumulative Volume Delta를 계산한다.

매수 체결량 - 매도 체결량의 누적값이다.
양수: 매수 압력(accumulation), 음수: 매도 압력(distribution)이다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.websocket.models import CVDValue, TradeEvent

_logger = get_logger(__name__)

# 추세 판단 임계값이다 (누적 델타의 총 거래량 대비 비율)
_THRESHOLD_ACCUMULATION = 0.15
_THRESHOLD_DISTRIBUTION = -0.15


def _classify_trend(delta: float, total_volume: int) -> str:
    """CVD 추세를 분류한다. 총 거래량 대비 비율로 판단한다."""
    if total_volume == 0:
        return "neutral"
    ratio = delta / total_volume
    if ratio > _THRESHOLD_ACCUMULATION:
        return "accumulation"
    if ratio < _THRESHOLD_DISTRIBUTION:
        return "distribution"
    return "neutral"


def _classify_by_side(trade: TradeEvent) -> int:
    """체결의 side 필드로 매수/매도를 분류한다.

    buy: +volume, sell: -volume, 불명: 0이다.
    """
    if trade.side == "buy":
        return trade.volume
    if trade.side == "sell":
        return -trade.volume
    return 0


def calculate_cvd(trades: list[TradeEvent]) -> CVDValue:
    """체결 목록에서 CVD를 계산한다.

    각 체결의 side 정보로 매수/매도 거래량을 누적한다.
    side가 없는 체결은 무시한다.
    """
    if not trades:
        return CVDValue(delta=0.0, trend="neutral")
    cumulative = 0
    total_volume = 0
    for trade in trades:
        delta = _classify_by_side(trade)
        cumulative += delta
        total_volume += trade.volume
    trend = _classify_trend(float(cumulative), total_volume)
    return CVDValue(delta=float(cumulative), trend=trend)
