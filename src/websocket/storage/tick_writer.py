"""FW 틱 기록기 -- 체결 데이터를 DB에 배치 저장한다.

TradeEvent를 모아서 일괄 INSERT한다. 실시간 틱 데이터 영속화 용도이다.
SessionFactory를 주입받아 DB 접근한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text

from src.common.logger import get_logger
from src.websocket.models import TradeEvent, WriteResult

if TYPE_CHECKING:
    from src.common.database_gateway import SessionFactory

_logger = get_logger(__name__)

# 배치 크기 상수이다
_DEFAULT_BATCH_SIZE = 100

# 틱 데이터 INSERT SQL -- tick_data 테이블 스키마(id, ticker, price, volume, timestamp, created_at)에 맞춘다
_INSERT_SQL = text("""
    INSERT INTO tick_data (id, ticker, price, volume, timestamp, created_at)
    VALUES (:id, :ticker, :price, :volume, :timestamp, :created_at)
""")


def _event_to_params(event: TradeEvent) -> dict:
    """TradeEvent를 SQL 파라미터 딕셔너리로 변환한다."""
    return {
        "id": str(uuid.uuid4()),
        "ticker": event.ticker,
        "price": event.price,
        "volume": event.volume,
        "timestamp": event.time,
        "created_at": datetime.now(tz=timezone.utc),
    }


class TickWriter:
    """체결 데이터 DB 기록기이다.

    버퍼에 TradeEvent를 모아두고 배치 크기에 도달하면 일괄 INSERT한다.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        """SessionFactory와 배치 크기로 초기화한다."""
        self._sf = session_factory
        self._batch_size = batch_size
        self._buffer: list[TradeEvent] = []

    async def add(self, event: TradeEvent) -> WriteResult | None:
        """버퍼에 이벤트를 추가한다. 배치 크기 도달 시 자동 flush한다."""
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            return await self.flush()
        return None

    async def flush(self) -> WriteResult:
        """버퍼의 모든 이벤트를 DB에 일괄 저장한다."""
        if not self._buffer:
            return WriteResult(success=True, rows_written=0)
        events = list(self._buffer)
        self._buffer.clear()
        params = [_event_to_params(e) for e in events]
        try:
            async with self._sf.get_session() as session:
                await session.execute(_INSERT_SQL, params)
            _logger.debug("틱 데이터 %d건 저장 완료", len(params))
            return WriteResult(success=True, rows_written=len(params))
        except Exception as exc:
            _logger.error("틱 데이터 저장 실패: %s", exc)
            return WriteResult(success=False, rows_written=0)

    @property
    def buffer_size(self) -> int:
        """현재 버퍼에 대기 중인 이벤트 수를 반환한다."""
        return len(self._buffer)
