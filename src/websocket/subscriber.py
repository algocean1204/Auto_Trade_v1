"""FW 구독 관리 -- 티커별 WebSocket 구독을 관리한다.

KIS TR_ID별 구독/해제 메시지를 전송하고 결과를 추적한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.websocket.models import SubscriptionResult

if TYPE_CHECKING:
    from src.websocket.connection import WebSocketConnection

_logger = get_logger(__name__)

# KIS 해외주식 실시간 TR_ID이다
_TR_TRADE = "HDFSCNT0"    # 체결
_TR_ORDERBOOK = "HDFSASP0"  # 호가
_TR_NOTICE = "H0GSCNI0"   # 체결통보

# 기본 구독 TR 목록이다 (체결 + 호가)
_DEFAULT_TRS = [_TR_TRADE, _TR_ORDERBOOK]


async def _subscribe_one(
    conn: WebSocketConnection,
    tr_id: str,
    ticker: str,
) -> bool:
    """단일 TR/티커 구독을 요청한다. 성공 시 True를 반환한다."""
    try:
        msg = conn.build_subscribe_message(tr_id, ticker)
        await conn.send(msg)
        _logger.debug("구독 요청: %s/%s", tr_id, ticker)
        return True
    except Exception as exc:
        _logger.error("구독 실패: %s/%s - %s", tr_id, ticker, exc)
        return False


async def _unsubscribe_one(
    conn: WebSocketConnection,
    tr_id: str,
    ticker: str,
) -> bool:
    """단일 TR/티커 구독 해제를 요청한다."""
    try:
        msg = conn.build_unsubscribe_message(tr_id, ticker)
        await conn.send(msg)
        _logger.debug("구독 해제: %s/%s", tr_id, ticker)
        return True
    except Exception as exc:
        _logger.error("구독 해제 실패: %s/%s - %s", tr_id, ticker, exc)
        return False


async def subscribe_tickers(
    tickers: list[str],
    connection: WebSocketConnection,
    tr_ids: list[str] | None = None,
) -> SubscriptionResult:
    """여러 티커를 구독한다.

    각 티커에 대해 지정된 TR(기본: 체결+호가)을 모두 구독 요청한다.
    """
    target_trs = tr_ids or _DEFAULT_TRS
    subscribed: list[str] = []
    failed: list[str] = []
    for ticker in tickers:
        ticker_ok = True
        for tr_id in target_trs:
            success = await _subscribe_one(connection, tr_id, ticker)
            if not success:
                ticker_ok = False
        if ticker_ok:
            subscribed.append(ticker)
        else:
            failed.append(ticker)
    _logger.info("구독 완료: %d 성공, %d 실패", len(subscribed), len(failed))
    return SubscriptionResult(subscribed=subscribed, failed=failed)


async def unsubscribe_tickers(
    tickers: list[str],
    connection: WebSocketConnection,
    tr_ids: list[str] | None = None,
) -> SubscriptionResult:
    """여러 티커의 구독을 해제한다."""
    target_trs = tr_ids or _DEFAULT_TRS
    unsubscribed: list[str] = []
    failed: list[str] = []
    for ticker in tickers:
        ticker_ok = True
        for tr_id in target_trs:
            success = await _unsubscribe_one(connection, tr_id, ticker)
            if not success:
                ticker_ok = False
        if ticker_ok:
            unsubscribed.append(ticker)
        else:
            failed.append(ticker)
    _logger.info("구독 해제 완료: %d 성공, %d 실패", len(unsubscribed), len(failed))
    return SubscriptionResult(subscribed=unsubscribed, failed=failed)
