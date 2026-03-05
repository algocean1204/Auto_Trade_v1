"""FW 호가창 핸들러 -- 실시간 호가 메시지를 OrderbookSnapshot으로 변환한다.

KIS HDFSASP0(해외주식 실시간 호가) TR을 파싱한다.
매수 10단계, 매도 10단계 호가를 구조화한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.logger import get_logger
from src.websocket.models import OrderbookSnapshot, ParsedMessage

_logger = get_logger(__name__)

# KIS 해외주식 호가 필드 인덱스이다
_IDX_TICKER = 0
_IDX_TIME = 1
# 매도 호가: 인덱스 2~21 (가격, 잔량 번갈아 10단계)
_IDX_ASK_START = 2
# 매수 호가: 인덱스 22~41
_IDX_BID_START = 22
_LEVELS = 10


def _safe_float(value: str) -> float:
    """안전하게 float 변환한다."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(value: str) -> int:
    """안전하게 int 변환한다."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _parse_levels(
    fields: list[str], start_idx: int,
) -> list[dict[str, float | int]]:
    """호가 10단계를 파싱하여 [{price, volume}] 리스트로 반환한다."""
    levels: list[dict[str, float | int]] = []
    for i in range(_LEVELS):
        price_idx = start_idx + (i * 2)
        vol_idx = price_idx + 1
        if vol_idx >= len(fields):
            break
        price = _safe_float(fields[price_idx])
        volume = _safe_int(fields[vol_idx])
        if price > 0:
            levels.append({"price": price, "volume": volume})
    return levels


def handle_orderbook(message: ParsedMessage) -> OrderbookSnapshot | None:
    """ParsedMessage를 OrderbookSnapshot으로 변환한다.

    호가 메시지가 아니거나 필드가 부족하면 None을 반환한다.
    """
    if message.type != "orderbook":
        return None
    fields: list[str] = message.data.get("fields", [])
    # 최소 42개 필드 필요 (티커 + 시간 + 매도10단계 + 매수10단계)
    if len(fields) < 42:
        _logger.debug("호가 필드 부족: %d개", len(fields))
        return None
    ticker = fields[_IDX_TICKER].strip()
    if not ticker:
        return None
    asks = _parse_levels(fields, _IDX_ASK_START)
    bids = _parse_levels(fields, _IDX_BID_START)
    return OrderbookSnapshot(
        ticker=ticker,
        bids=bids,
        asks=asks,
        timestamp=datetime.now(tz=timezone.utc),
    )
