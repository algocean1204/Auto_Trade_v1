"""FW 공지 핸들러 -- 체결통보/시스템 공지를 NoticeEvent로 변환한다.

KIS H0GSCNI0(해외주식 체결통보) TR과 시스템 알림을 처리한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.common.logger import get_logger
from src.websocket.models import NoticeEvent, ParsedMessage

_logger = get_logger(__name__)

# KIS 체결통보 필드 인덱스이다
_IDX_ORDER_ID = 1
_IDX_ORDER_TYPE = 4
_IDX_TICKER = 8
_IDX_QTY = 11
_IDX_PRICE = 12


def _build_trade_notice(fields: list[str]) -> str:
    """체결통보 필드로부터 알림 내용 문자열을 생성한다."""
    ticker = fields[_IDX_TICKER].strip() if len(fields) > _IDX_TICKER else "?"
    qty = fields[_IDX_QTY].strip() if len(fields) > _IDX_QTY else "?"
    price = fields[_IDX_PRICE].strip() if len(fields) > _IDX_PRICE else "?"
    order_id = fields[_IDX_ORDER_ID].strip() if len(fields) > _IDX_ORDER_ID else "?"
    return f"체결통보: {ticker} {qty}주 @ ${price} (주문번호: {order_id})"


def _handle_pipe_notice(message: ParsedMessage) -> NoticeEvent | None:
    """파이프 형식 체결통보를 NoticeEvent로 변환한다."""
    fields: list[str] = message.data.get("fields", [])
    if len(fields) < 13:
        _logger.debug("체결통보 필드 부족: %d개", len(fields))
        return None
    content = _build_trade_notice(fields)
    return NoticeEvent(
        type="trade_notice",
        content=content,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _handle_json_notice(message: ParsedMessage) -> NoticeEvent | None:
    """JSON 형식 시스템 공지를 NoticeEvent로 변환한다."""
    data = message.data
    body = data.get("body", {})
    content = json.dumps(body, ensure_ascii=False, default=str)
    return NoticeEvent(
        type="system_notice",
        content=content,
        timestamp=datetime.now(tz=timezone.utc),
    )


def handle_notice(message: ParsedMessage) -> NoticeEvent | None:
    """ParsedMessage를 NoticeEvent로 변환한다.

    공지 타입이 아니면 None을 반환한다.
    """
    if message.type == "notice":
        return _handle_pipe_notice(message)
    if message.type == "subscribe_ack":
        return _handle_json_notice(message)
    return None
