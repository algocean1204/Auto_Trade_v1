"""FW WebSocket 매니저 -- 전체 생명주기를 오케스트레이션한다.

연결, 구독, 메시지 수신, 핸들러 디스패치, 인디케이터 업데이트를 관리한다.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.websocket.handlers.notice_handler import handle_notice
from src.websocket.handlers.orderbook_handler import handle_orderbook
from src.websocket.handlers.trade_handler import handle_trade
from src.websocket.indicators.cvd import calculate_cvd
from src.websocket.indicators.execution_strength import calculate_strength
from src.websocket.indicators.obi import calculate_obi
from src.websocket.indicators.vpin import calculate_vpin
from src.websocket.models import ManagerState, TradeEvent
from src.websocket.parser import parse_message
from src.websocket.subscriber import subscribe_tickers, unsubscribe_tickers

if TYPE_CHECKING:
    from src.websocket.connection import WebSocketConnection
    from src.websocket.storage.cache_publisher import CachePublisher
    from src.websocket.storage.tick_writer import TickWriter

_logger = get_logger(__name__)

# 인디케이터 계산용 체결 이력 최대 보관 수이다
_MAX_TRADE_HISTORY = 500


class WebSocketManager:
    """KIS WebSocket 전체 생명주기 관리자이다.

    연결, 메시지 수신 루프, 핸들러 디스패치, 인디케이터 업데이트,
    DB 기록, 캐시 발행을 오케스트레이션한다.
    """

    def __init__(
        self,
        connection: WebSocketConnection,
        tick_writer: TickWriter | None = None,
        publisher: CachePublisher | None = None,
    ) -> None:
        """연결 및 저장소 의존성으로 초기화한다."""
        self._conn = connection
        self._writer = tick_writer
        self._publisher = publisher
        self._running = False
        self._subscribed: list[str] = []
        self._last_message_time: datetime | None = None
        # 티커별 체결 이력이다
        self._trade_history: dict[str, list[TradeEvent]] = defaultdict(list)
        # 최신 인디케이터 값을 캐싱한다
        self._indicators: dict[str, dict] = {}

    async def start(self, tickers: list[str]) -> None:
        """WebSocket 연결 및 구독을 시작한다."""
        await self._conn.connect()
        result = await subscribe_tickers(tickers, self._conn)
        self._subscribed = result.subscribed
        self._running = True
        _logger.info("WebSocketManager 시작: %d 티커 구독", len(self._subscribed))

    async def stop(self) -> None:
        """구독 해제 및 연결 종료한다."""
        self._running = False
        if self._subscribed:
            await unsubscribe_tickers(self._subscribed, self._conn)
            self._subscribed.clear()
        if self._writer:
            await self._writer.flush()
        await self._conn.disconnect()
        _logger.info("WebSocketManager 종료 완료")

    async def run_loop(self) -> None:
        """메시지 수신 루프를 실행한다. stop() 호출 시 종료된다."""
        while self._running:
            try:
                raw = await self._conn.receive()
                self._last_message_time = datetime.now(tz=timezone.utc)
                await self._dispatch(raw)
            except ConnectionError:
                _logger.warning("WebSocket 연결 끊김, 재연결 시도")
                await self._reconnect()
            except Exception as exc:
                _logger.error("메시지 처리 오류: %s", exc)
                await asyncio.sleep(0.1)

    async def _reconnect(self) -> None:
        """재연결을 시도한다."""
        try:
            await self._conn.connect()
            if self._subscribed:
                await subscribe_tickers(self._subscribed, self._conn)
            _logger.info("WebSocket 재연결 성공")
        except Exception as exc:
            _logger.error("재연결 실패: %s", exc)
            self._running = False

    async def _dispatch(self, raw: str) -> None:
        """파싱된 메시지를 적절한 핸들러로 디스패치한다."""
        message = parse_message(raw)
        if message.type == "trade":
            await self._handle_trade(message)
        elif message.type == "orderbook":
            await self._handle_orderbook(message)
        elif message.type == "notice":
            handle_notice(message)
        elif message.type == "heartbeat":
            # heartbeat은 별도 처리 불필요하다
            pass

    async def _handle_trade(self, message) -> None:
        """체결 메시지를 처리하고 인디케이터를 갱신한다."""
        event = handle_trade(message)
        if event is None:
            return
        # 이력 관리한다
        history = self._trade_history[event.ticker]
        history.append(event)
        if len(history) > _MAX_TRADE_HISTORY:
            self._trade_history[event.ticker] = history[-_MAX_TRADE_HISTORY:]
        # 인디케이터 갱신한다
        self._update_trade_indicators(event.ticker)
        # 저장소 기록한다
        if self._writer:
            await self._writer.add(event)
        if self._publisher:
            await self._publisher.publish_trade(event)

    def _update_trade_indicators(self, ticker: str) -> None:
        """체결 기반 인디케이터(VPIN, CVD, 체결강도)를 갱신한다."""
        history = self._trade_history.get(ticker, [])
        if not history:
            return
        vpin = calculate_vpin(history)
        cvd = calculate_cvd(history)
        strength = calculate_strength(history)
        self._indicators[ticker] = {
            "vpin": vpin.model_dump(),
            "cvd": cvd.model_dump(),
            "strength": strength.model_dump(),
        }

    async def _handle_orderbook(self, message) -> None:
        """호가 메시지를 처리하고 OBI를 갱신한다."""
        snapshot = handle_orderbook(message)
        if snapshot is None:
            return
        obi = calculate_obi(snapshot)
        indicators = self._indicators.setdefault(snapshot.ticker, {})
        indicators["obi"] = obi.model_dump()
        if self._publisher:
            await self._publisher.publish_orderbook(snapshot)

    def get_state(self) -> ManagerState:
        """현재 매니저 상태를 반환한다."""
        return ManagerState(
            connected=self._conn.connected,
            active_subscriptions=len(self._subscribed),
            last_message_time=self._last_message_time,
        )

    def get_indicators(self, ticker: str) -> dict:
        """특정 티커의 최신 인디케이터 값을 반환한다."""
        return self._indicators.get(ticker, {})
