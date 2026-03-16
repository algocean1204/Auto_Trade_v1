"""
EventBus (C0.10) -- Feature 간 비동기 이벤트 발행/구독을 관리한다.

Feature 간 직접 호출 대신 이벤트 기반 통신을 사용하여
모듈 간 결합도를 낮춘다.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.common.logger import get_logger

_logger = get_logger(__name__)

_instance: EventBus | None = None


# ---------------------------------------------------------------------------
# 이벤트 타입 열거형 -- 허용된 이벤트만 발행 가능하다
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """시스템에서 발생하는 이벤트 타입 목록이다."""

    ARTICLE_COLLECTED = "ArticleCollected"
    TRADING_DECISION = "TradingDecision"
    POSITION_CHANGED = "PositionChanged"
    EMERGENCY_LIQUIDATION = "EmergencyLiquidation"
    CRASH_DETECTED = "CrashDetected"
    EOD_STARTED = "EODStarted"
    BEAST_ENTRY = "BeastEntry"
    PYRAMID_TRIGGERED = "PyramidTriggered"
    TILT_DETECTED = "TiltDetected"
    INFRA_HEALTH_CHANGED = "InfraHealthChanged"
    WEEKLY_REPORT_GENERATED = "WeeklyReportGenerated"


# ---------------------------------------------------------------------------
# 이벤트 배달 결과 모델
# ---------------------------------------------------------------------------

class EventDeliveryResult(BaseModel):
    """이벤트 배달 결과이다."""

    event_type: str
    delivered_to: int
    failed: int
    timestamp: datetime


# 핸들러 타입: 동기/비동기 모두 허용한다
EventHandler = Callable[[BaseModel], Coroutine[Any, Any, None]] | Callable[[BaseModel], None]


# ---------------------------------------------------------------------------
# EventBus 본체
# ---------------------------------------------------------------------------

class EventBus:
    """비동기 이벤트 버스이다. Feature 간 직접 호출 대신 이벤트로 통신한다."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """이벤트 타입에 핸들러를 등록한다. 중복 등록은 무시한다."""
        handlers = self._handlers[event_type]
        if handler in handlers:
            _logger.debug(
                "핸들러 이미 등록됨 (건너뜀): %s -> %s",
                event_type,
                getattr(handler, "__name__", str(handler)),
            )
            return
        handlers.append(handler)
        _logger.debug(
            "이벤트 구독 등록: %s -> %s",
            event_type,
            getattr(handler, "__name__", str(handler)),
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """이벤트 타입에서 핸들러를 제거한다."""
        handlers = self._handlers.get(event_type, [])
        try:
            handlers.remove(handler)
            _logger.debug(
                "이벤트 구독 해제: %s -> %s",
                event_type,
                getattr(handler, "__name__", str(handler)),
            )
        except ValueError:
            _logger.warning(
                "해제할 핸들러를 찾을 수 없다: %s -> %s",
                event_type,
                getattr(handler, "__name__", str(handler)),
            )

    async def publish(
        self,
        event_type: str,
        payload: BaseModel,
    ) -> EventDeliveryResult:
        """이벤트를 발행하고 등록된 모든 핸들러에 배달한다.

        핸들러 실패는 개별 격리하여 다른 핸들러에 영향을 주지 않는다.
        """
        handlers = self._handlers.get(event_type, [])
        delivered = 0
        failed = 0

        _logger.info(
            "이벤트 발행: %s (구독자 %d명)",
            event_type,
            len(handlers),
        )

        for handler in handlers:
            try:
                result = handler(payload)
                # 비동기 핸들러인 경우 await 한다
                if asyncio.iscoroutine(result):
                    await result
                delivered += 1
            except Exception:
                failed += 1
                handler_name = getattr(handler, "__name__", str(handler))
                _logger.exception(
                    "이벤트 핸들러 실패: %s -> %s",
                    event_type,
                    handler_name,
                )

        return EventDeliveryResult(
            event_type=event_type,
            delivered_to=delivered,
            failed=failed,
            timestamp=datetime.now(tz=timezone.utc),
        )

    def clear(self) -> None:
        """모든 이벤트 구독을 해제한다. 테스트/종료 시 사용한다."""
        count = sum(len(h) for h in self._handlers.values())
        self._handlers.clear()
        _logger.info("이벤트 버스 초기화 완료: %d개 핸들러 제거", count)

    def subscriber_count(self, event_type: str) -> int:
        """특정 이벤트 타입의 구독자 수를 반환한다."""
        return len(self._handlers.get(event_type, []))


# ---------------------------------------------------------------------------
# 팩토리 함수
# ---------------------------------------------------------------------------

def get_event_bus() -> EventBus:
    """EventBus 싱글톤을 반환한다."""
    global _instance
    if _instance is None:
        _instance = EventBus()
        _logger.info("EventBus 싱글톤 생성 완료")
    return _instance


def reset_event_bus() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    if _instance is not None:
        _instance.clear()
    _instance = None
