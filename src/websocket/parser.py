"""FW WebSocket 메시지 파서 -- KIS 프로토콜 메시지를 파싱한다.

KIS WebSocket 프로토콜: | 구분자, 헤더(TR_ID) + 본문(^ 구분) 형식이다.
JSON 응답(구독 확인, heartbeat)과 실시간 데이터를 분리 처리한다.
"""
from __future__ import annotations

import json

from src.common.logger import get_logger
from src.websocket.models import ParsedMessage

_logger = get_logger(__name__)

# KIS TR_ID → 메시지 타입 매핑이다
_TR_TYPE_MAP: dict[str, str] = {
    "HDFSCNT0": "trade",      # 해외주식 체결
    "HDFSASP0": "orderbook",  # 해외주식 호가
    "H0GSCNI0": "notice",     # 해외주식 체결통보
}


def _parse_json_message(raw: str) -> ParsedMessage | None:
    """JSON 형식 메시지(heartbeat, 구독 응답)를 파싱한다."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    header = data.get("header", {})
    tr_id = header.get("tr_id", "")
    # heartbeat 응답이다
    if tr_id == "PINGPONG" or header.get("tr_type") == "P":
        return ParsedMessage(type="heartbeat", data=data, raw_length=len(raw))
    # 구독 확인 응답이다
    return ParsedMessage(type="subscribe_ack", data=data, raw_length=len(raw))


def _parse_pipe_message(raw: str) -> ParsedMessage:
    """파이프(|) 구분자 형식 실시간 데이터를 파싱한다."""
    parts = raw.split("|")
    if len(parts) < 4:
        return ParsedMessage(type="unknown", data={"raw": raw}, raw_length=len(raw))
    # parts[0]: 암호화+데이터 길이, parts[1]: TR_ID, parts[2]: 건수, parts[3]: 데이터
    tr_id = parts[1].strip()
    count_str = parts[2].strip()
    body = parts[3]
    msg_type = _TR_TYPE_MAP.get(tr_id, "unknown")
    count = _safe_int(count_str)
    fields = body.split("^")
    return ParsedMessage(
        type=msg_type,
        data={"tr_id": tr_id, "count": count, "fields": fields},
        raw_length=len(raw),
    )


def _safe_int(value: str) -> int:
    """안전하게 정수 변환한다. 실패 시 0을 반환한다."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def parse_message(raw: str | bytes) -> ParsedMessage:
    """수신 메시지를 파싱하여 ParsedMessage를 반환한다.

    JSON(heartbeat/구독 응답)과 파이프 구분자(실시간 데이터)를 자동 판별한다.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    raw = raw.strip()
    if not raw:
        return ParsedMessage(type="empty", data={}, raw_length=0)
    # JSON 메시지 시도 (중괄호로 시작)
    if raw.startswith("{"):
        result = _parse_json_message(raw)
        if result is not None:
            return result
    # 파이프 구분자 형식이다
    if "|" in raw:
        return _parse_pipe_message(raw)
    _logger.debug("알 수 없는 메시지 형식: %.100s", raw)
    return ParsedMessage(type="unknown", data={"raw": raw}, raw_length=len(raw))
