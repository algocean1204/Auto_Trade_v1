"""FW 체결 핸들러 -- 실시간 체결 메시지를 TradeEvent로 변환한다.

KIS HDFSCNT0(해외주식 실시간 체결) TR을 파싱한다.
필드 순서: 종목코드, 체결시간, 현재가, 거래량, 매수/매도 등이다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.logger import get_logger
from src.websocket.models import ParsedMessage, TradeEvent

_logger = get_logger(__name__)

# KIS 해외주식 체결 필드 인덱스 (HDFSCNT0)이다
_IDX_TICKER = 0
_IDX_TIME = 1
_IDX_PRICE = 2
_IDX_CHANGE = 3
_IDX_CHANGE_SIGN = 4
_IDX_CHANGE_RATE = 5
_IDX_VOLUME = 12
_IDX_SIDE = 14


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


def _parse_time(time_str: str) -> datetime:
    """KIS 체결시간(HHMMSS)을 UTC datetime으로 변환한다."""
    try:
        hour = int(time_str[:2])
        minute = int(time_str[2:4])
        second = int(time_str[4:6])
        now = datetime.now(tz=timezone.utc)
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    except (ValueError, IndexError):
        return datetime.now(tz=timezone.utc)


def _determine_side(side_code: str) -> str:
    """매수/매도 구분 코드를 문자열로 변환한다."""
    # KIS: 1=매수, 2=매도
    if side_code == "1":
        return "buy"
    if side_code == "2":
        return "sell"
    return ""


def handle_trade(message: ParsedMessage) -> TradeEvent | None:
    """ParsedMessage를 TradeEvent로 변환한다.

    체결 메시지가 아니거나 필드가 부족하면 None을 반환한다.
    """
    if message.type != "trade":
        return None
    fields: list[str] = message.data.get("fields", [])
    if len(fields) < 15:
        _logger.debug("체결 필드 부족: %d개", len(fields))
        return None
    ticker = fields[_IDX_TICKER].strip()
    price = _safe_float(fields[_IDX_PRICE])
    volume = _safe_int(fields[_IDX_VOLUME])
    trade_time = _parse_time(fields[_IDX_TIME])
    side = _determine_side(fields[_IDX_SIDE].strip())
    if not ticker or price <= 0:
        _logger.debug("유효하지 않은 체결 데이터: ticker=%s, price=%s", ticker, price)
        return None
    return TradeEvent(
        ticker=ticker,
        price=price,
        volume=volume,
        time=trade_time,
        side=side,
    )
