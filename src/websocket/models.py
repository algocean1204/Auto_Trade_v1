"""FW WebSocket -- 공용 모델이다."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ConnectionState(BaseModel):
    """WebSocket 연결 상태를 나타낸다."""

    connected: bool
    subscriptions: list[str] = []
    last_message_time: datetime | None = None


class ParsedMessage(BaseModel):
    """파싱된 KIS WebSocket 메시지이다."""

    type: str  # trade/orderbook/notice/heartbeat
    data: dict
    raw_length: int = 0


class TradeEvent(BaseModel):
    """실시간 체결 이벤트이다."""

    ticker: str
    price: float
    volume: int
    time: datetime
    side: str = ""  # buy/sell


class OrderbookSnapshot(BaseModel):
    """호가창 스냅샷이다."""

    ticker: str
    bids: list[dict]  # [{price, volume}]
    asks: list[dict]
    timestamp: datetime


class NoticeEvent(BaseModel):
    """공지/알림 이벤트이다."""

    type: str
    content: str
    timestamp: datetime


class OBIValue(BaseModel):
    """Order Book Imbalance 계산 결과이다."""

    score: float
    direction: str


class VPINValue(BaseModel):
    """VPIN 계산 결과이다."""

    score: float
    toxicity: str  # low/medium/high/extreme


class CVDValue(BaseModel):
    """Cumulative Volume Delta 계산 결과이다."""

    delta: float
    trend: str  # accumulation/distribution/neutral


class StrengthValue(BaseModel):
    """체결 강도 계산 결과이다."""

    score: float


class WriteResult(BaseModel):
    """DB 기록 결과이다."""

    success: bool
    rows_written: int


class PublishResult(BaseModel):
    """캐시 발행 결과이다."""

    published: bool
    channel: str


class SubscriptionResult(BaseModel):
    """구독 요청 결과이다."""

    subscribed: list[str]
    failed: list[str]


class ManagerState(BaseModel):
    """WebSocket 매니저 상태이다."""

    connected: bool
    active_subscriptions: int
    last_message_time: datetime | None = None
