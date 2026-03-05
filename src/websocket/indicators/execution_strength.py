"""FW 체결 강도 계산기 -- 매수/매도 체결 비율을 측정한다.

체결 강도 = (매수 체결량 / 매도 체결량) * 100
100 이상: 매수 우세, 100 미만: 매도 우세이다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.websocket.models import StrengthValue, TradeEvent

_logger = get_logger(__name__)

# 정규화 범위이다 (0 ~ 200을 0.0 ~ 1.0으로 매핑)
_NORMALIZE_MAX = 200.0


def _sum_by_side(
    trades: list[TradeEvent],
) -> tuple[int, int]:
    """매수/매도 체결량을 분리 합산한다."""
    buy_vol = 0
    sell_vol = 0
    for trade in trades:
        if trade.side == "buy":
            buy_vol += trade.volume
        elif trade.side == "sell":
            sell_vol += trade.volume
    return buy_vol, sell_vol


def _normalize(raw_strength: float) -> float:
    """원시 체결 강도를 0.0~1.0 범위로 정규화한다.

    0: 완전 매도 우세, 0.5: 균형, 1.0: 완전 매수 우세이다.
    """
    clamped = max(0.0, min(_NORMALIZE_MAX, raw_strength))
    return round(clamped / _NORMALIZE_MAX, 4)


def calculate_strength(trades: list[TradeEvent]) -> StrengthValue:
    """체결 목록에서 체결 강도를 계산한다.

    side 정보가 없는 체결이 많으면 0.5(중립)에 가까워진다.
    빈 목록이면 score=0.5를 반환한다.
    """
    if not trades:
        return StrengthValue(score=0.5)
    buy_vol, sell_vol = _sum_by_side(trades)
    if sell_vol == 0 and buy_vol == 0:
        return StrengthValue(score=0.5)
    if sell_vol == 0:
        # 매도 없으면 최대 강도이다
        return StrengthValue(score=1.0)
    raw_strength = (buy_vol / sell_vol) * 100.0
    score = _normalize(raw_strength)
    return StrengthValue(score=score)
