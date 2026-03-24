"""FW 캐시 발행기 -- 실시간 이벤트를 Pub/Sub 채널에 발행한다.

TradeEvent, OrderbookSnapshot을 JSON 직렬화하여 채널에 발행한다.
동시에 OrderFlowAggregator가 읽는 KV 스토어(order_flow:raw:{ticker})에도 기록한다.
CacheClient를 주입받아 캐시에 접근한다.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.websocket.models import (
    OrderbookSnapshot,
    PublishResult,
    TradeEvent,
)

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient

_logger = get_logger(__name__)

# 캐시 채널 접두사이다
_CHANNEL_TRADE = "ws:trade"
_CHANNEL_ORDERBOOK = "ws:orderbook"

# OrderFlowAggregator가 읽는 KV 키 접두사이다
_ORDER_FLOW_KEY = "order_flow:raw:{ticker}"

# KV 스토어 설정이다 — 실시간 데이터이므로 짧은 TTL을 사용한다
_ORDER_FLOW_TTL_SECONDS: int = 30
# 슬라이딩 윈도우에 보관할 최대 체결 건수이다
_MAX_TRADE_WINDOW: int = 200


def _serialize_trade(event: TradeEvent) -> str:
    """TradeEvent를 JSON 문자열로 직렬화한다."""
    return json.dumps(
        {
            "ticker": event.ticker,
            "price": event.price,
            "volume": event.volume,
            "time": str(event.time),
            "side": event.side,
        },
        ensure_ascii=False,
        default=str,
    )


def _serialize_orderbook(snapshot: OrderbookSnapshot) -> str:
    """OrderbookSnapshot을 JSON 문자열로 직렬화한다."""
    return json.dumps(
        {
            "ticker": snapshot.ticker,
            "bids": snapshot.bids,
            "asks": snapshot.asks,
            "timestamp": str(snapshot.timestamp),
        },
        ensure_ascii=False,
        default=str,
    )


def _trade_to_dict(event: TradeEvent) -> dict:
    """TradeEvent를 OrderFlowAggregator가 기대하는 dict 형식으로 변환한다."""
    return {
        "price": event.price,
        "volume": event.volume,
        "time": str(event.time),
        "side": event.side,
    }


class CachePublisher:
    """실시간 이벤트를 캐시 채널에 발행하는 퍼블리셔이다.

    Pub/Sub 발행과 동시에 OrderFlowAggregator가 읽는 KV 스토어에도
    슬라이딩 윈도우 형태로 데이터를 적재한다.
    """

    def __init__(self, cache: CacheClient) -> None:
        """CacheClient를 주입받아 초기화한다."""
        self._cache = cache

    async def publish_trade(self, event: TradeEvent) -> PublishResult:
        """체결 이벤트를 캐시 채널에 발행하고 KV 스토어에도 기록한다.

        Pub/Sub 채널 발행 후, order_flow:raw:{ticker} 키에 슬라이딩 윈도우로
        최근 체결 목록을 유지한다. OrderFlowAggregator가 이 키를 직접 읽는다.
        """
        channel = f"{_CHANNEL_TRADE}:{event.ticker}"
        message = _serialize_trade(event)
        try:
            await self._cache.publish(channel, message)
            # KV 스토어에도 체결 데이터를 누적하여 OrderFlowAggregator가 읽을 수 있게 한다
            await self._append_trade_to_kv(event)
            return PublishResult(published=True, channel=channel)
        except Exception as exc:
            _logger.error("Trade 발행 실패 (%s): %s", channel, exc)
            return PublishResult(published=False, channel=channel)

    async def publish_orderbook(
        self, snapshot: OrderbookSnapshot,
    ) -> PublishResult:
        """호가창 스냅샷을 캐시 채널에 발행하고 KV 스토어에도 기록한다.

        Pub/Sub 채널 발행 후, order_flow:raw:{ticker} 키의 bids/asks를
        최신 스냅샷으로 교체한다. OrderFlowAggregator가 이 키를 직접 읽는다.
        """
        channel = f"{_CHANNEL_ORDERBOOK}:{snapshot.ticker}"
        message = _serialize_orderbook(snapshot)
        try:
            await self._cache.publish(channel, message)
            # KV 스토어의 호가 데이터를 최신 스냅샷으로 갱신한다
            await self._update_orderbook_in_kv(snapshot)
            return PublishResult(published=True, channel=channel)
        except Exception as exc:
            _logger.error("Orderbook 발행 실패 (%s): %s", channel, exc)
            return PublishResult(published=False, channel=channel)

    async def _append_trade_to_kv(self, event: TradeEvent) -> None:
        """체결 이벤트를 KV 스토어의 슬라이딩 윈도우에 원자적으로 추가한다.

        atomic_dict_update로 읽기-수정-쓰기를 Lock 내에서 수행하여
        동시 체결 이벤트 간 데이터 유실을 방지한다.
        """
        key = _ORDER_FLOW_KEY.format(ticker=event.ticker)
        trade_dict = _trade_to_dict(event)
        max_window = _MAX_TRADE_WINDOW

        def _updater(data: dict) -> dict:
            trades: list = data.get("trades", [])
            trades.append(trade_dict)
            if len(trades) > max_window:
                trades = trades[-max_window:]
            data["trades"] = trades
            return data

        try:
            await self._cache.atomic_dict_update(
                key, _updater,
                default={"trades": [], "bids": [], "asks": []},
                ttl=_ORDER_FLOW_TTL_SECONDS,
            )
        except Exception as exc:
            _logger.warning("Trade KV 적재 실패 (%s): %s", event.ticker, exc)

    async def _update_orderbook_in_kv(self, snapshot: OrderbookSnapshot) -> None:
        """호가창 스냅샷을 KV 스토어에 원자적으로 갱신한다.

        atomic_dict_update로 trades를 유지하면서 bids/asks만 교체한다.
        """
        key = _ORDER_FLOW_KEY.format(ticker=snapshot.ticker)
        bids = snapshot.bids
        asks = snapshot.asks

        def _updater(data: dict) -> dict:
            data["bids"] = bids
            data["asks"] = asks
            return data

        try:
            await self._cache.atomic_dict_update(
                key, _updater,
                default={"trades": [], "bids": [], "asks": []},
                ttl=_ORDER_FLOW_TTL_SECONDS,
            )
        except Exception as exc:
            _logger.warning("Orderbook KV 갱신 실패 (%s): %s", snapshot.ticker, exc)
