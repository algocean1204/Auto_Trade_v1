"""F3 지표 -- WebSocket 체결 데이터 기반 주문 흐름 집계이다."""
from __future__ import annotations

import json
import math

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.indicators.models import OrderFlowSnapshot

logger = get_logger(__name__)

_ORDER_FLOW_KEY: str = "order_flow:raw:{ticker}"
_VPIN_BUCKET_SIZE: int = 50  # VPIN 계산용 버킷 크기


def _calc_obi(bids: list[dict], asks: list[dict]) -> float:
    """OBI(Order Book Imbalance)를 계산한다. +1=매수 우세, -1=매도 우세이다."""
    bid_vol = sum(b.get("volume", 0) for b in bids)
    ask_vol = sum(a.get("volume", 0) for a in asks)
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def _calc_cvd(trades: list[dict]) -> float:
    """CVD(Cumulative Volume Delta)를 계산한다. 매수-매도 체결량 누적이다."""
    delta = 0.0
    for t in trades:
        vol = t.get("volume", 0)
        if t.get("side") == "buy":
            delta += vol
        else:
            delta -= vol
    return delta


def _calc_vpin(trades: list[dict], bucket_size: int) -> float:
    """VPIN(Volume-Synchronized Probability of Informed Trading)을 계산한다.

    체결 데이터를 일정 거래량 버킷으로 나누어 정보 거래 확률을 추정한다.
    """
    if len(trades) < bucket_size:
        return 0.0
    # 버킷 단위로 매수/매도 불균형을 측정한다
    buckets: list[float] = []
    current_buy = 0.0
    current_sell = 0.0
    count = 0
    for t in trades:
        vol = float(t.get("volume", 0))
        if t.get("side") == "buy":
            current_buy += vol
        else:
            current_sell += vol
        count += 1
        if count >= bucket_size:
            total = current_buy + current_sell
            if total > 0:
                buckets.append(abs(current_buy - current_sell) / total)
            current_buy = 0.0
            current_sell = 0.0
            count = 0
    if not buckets:
        return 0.0
    return sum(buckets) / len(buckets)


def _calc_execution_strength(trades: list[dict]) -> float:
    """체결 강도를 계산한다. 최근 체결의 매수/매도 비율이다."""
    if not trades:
        return 0.5
    recent = trades[-100:] if len(trades) > 100 else trades
    buy_count = sum(1 for t in recent if t.get("side") == "buy")
    return buy_count / len(recent)


class OrderFlowAggregator:
    """WebSocket 체결 데이터를 집계하여 주문 흐름 지표를 생성한다."""

    def __init__(self, cache: CacheClient) -> None:
        """CacheClient 의존성을 주입받는다."""
        self._cache = cache

    async def aggregate(self, ticker: str) -> OrderFlowSnapshot:
        """체결 데이터를 집계하여 주문 흐름 스냅샷을 반환한다.

        Args:
            ticker: 종목 코드

        Returns:
            OrderFlowSnapshot (OBI, CVD, VPIN, 체결 강도)
        """
        data = await self._load_flow_data(ticker)
        trades = data.get("trades", [])
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        obi = _calc_obi(bids, asks)
        cvd = _calc_cvd(trades)
        vpin = _calc_vpin(trades, _VPIN_BUCKET_SIZE)
        strength = _calc_execution_strength(trades)

        logger.debug(
            "%s 주문 흐름: OBI=%.4f, CVD=%.1f, VPIN=%.4f, strength=%.4f",
            ticker, obi, cvd, vpin, strength,
        )
        return OrderFlowSnapshot(
            obi=round(obi, 4),
            cvd=round(cvd, 2),
            vpin=round(vpin, 4),
            execution_strength=round(strength, 4),
        )

    async def _load_flow_data(self, ticker: str) -> dict:
        """Redis에서 주문 흐름 데이터를 조회한다."""
        key = _ORDER_FLOW_KEY.format(ticker=ticker)
        data = await self._cache.read_json(key)
        return data or {"trades": [], "bids": [], "asks": []}
