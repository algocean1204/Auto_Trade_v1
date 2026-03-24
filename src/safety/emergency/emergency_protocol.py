"""EmergencyProtocol (F6.3) -- 긴급 상황 시 전량 청산 및 매매 중단을 관리한다.

6가지 긴급 시나리오를 감지하고 적절한 조치를 취한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 상수 --
_HALT_DURATION_MINUTES: int = 30
_VPIN_COOLDOWN_MINUTES: int = 30


_ActionType = Literal["liquidate_all", "halt_trading", "reduce_exposure"]


class EmergencyAction(BaseModel):
    """긴급 조치 내용이다."""

    action_type: _ActionType
    reason: str
    triggered_at: datetime


class EmergencyResult(BaseModel):
    """긴급 조치 결과이다."""

    actions_taken: list[EmergencyAction]
    positions_liquidated: int = 0
    trading_halted: bool = False


# 긴급 시나리오별 심각도 임계값
_SCENARIO_CONFIG: dict[str, dict] = {
    "daily_loss": {
        "threshold": 0.5,
        "action": "halt_trading",
        "halt_minutes": _HALT_DURATION_MINUTES,
    },
    "consecutive_stops": {
        "threshold": 0.5,
        "action": "halt_trading",
        "halt_minutes": _HALT_DURATION_MINUTES,
    },
    "vix_spike": {
        "threshold": 0.7,
        "action": "reduce_exposure",
        "halt_minutes": 0,
    },
    "circuit_breaker": {
        "threshold": 0.3,
        "action": "liquidate_all",
        "halt_minutes": 60,
    },
    "api_failure": {
        "threshold": 0.5,
        "action": "halt_trading",
        "halt_minutes": 15,
    },
    "vpin_extreme": {
        "threshold": 0.4,
        "action": "reduce_exposure",
        "halt_minutes": _VPIN_COOLDOWN_MINUTES,
    },
}


class EmergencyProtocol:
    """긴급 프로토콜이다. 6가지 긴급 시나리오를 처리한다."""

    def __init__(self) -> None:
        """긴급 프로토콜을 초기화한다."""
        self._halt_until: datetime | None = None
        self._event_bus = get_event_bus()
        self._triggered_history: list[EmergencyAction] = []

    async def evaluate(
        self,
        trigger: str,
        severity: float,
    ) -> EmergencyResult:
        """긴급 상황을 평가하고 조치한다.

        Args:
            trigger: 긴급 시나리오 이름 (6가지 중 하나)
            severity: 심각도 0.0~1.0
        """
        config = _SCENARIO_CONFIG.get(trigger)
        if config is None:
            _logger.warning("알 수 없는 긴급 트리거: %s", trigger)
            return EmergencyResult(actions_taken=[])

        if severity < config["threshold"]:
            return EmergencyResult(actions_taken=[])

        now = datetime.now(tz=timezone.utc)
        action = self._build_action(
            cast(_ActionType, config["action"]), trigger, severity, now,
        )
        actions: list[EmergencyAction] = [action]

        # 매매 중단 설정
        halt_minutes = config["halt_minutes"]
        halted = False
        if halt_minutes > 0:
            self._halt_until = now + timedelta(
                minutes=halt_minutes,
            )
            halted = True

        self._triggered_history.append(action)
        _logger.error(
            "긴급 조치 발동: %s (심각도=%.2f) -> %s",
            trigger, severity, config["action"],
        )

        # 이벤트 버스에 긴급 청산 이벤트 발행
        if config["action"] == "liquidate_all":
            await self._publish_emergency(trigger)

        return EmergencyResult(
            actions_taken=actions,
            positions_liquidated=1 if config["action"] == "liquidate_all" else 0,
            trading_halted=halted,
        )

    def is_halted(self) -> bool:
        """현재 매매 중단 상태인지 반환한다."""
        if self._halt_until is None:
            return False
        now = datetime.now(tz=timezone.utc)
        if now >= self._halt_until:
            self._halt_until = None
            return False
        return True

    def reset(self) -> None:
        """일일 리셋한다."""
        self._halt_until = None
        self._triggered_history.clear()
        _logger.info("EmergencyProtocol 일일 리셋 완료")

    def get_history(self) -> list[EmergencyAction]:
        """발동 이력을 반환한다."""
        return list(self._triggered_history)

    def _build_action(
        self,
        action_type: _ActionType,
        trigger: str,
        severity: float,
        now: datetime,
    ) -> EmergencyAction:
        """긴급 조치 객체를 생성한다."""
        return EmergencyAction(
            action_type=action_type,
            reason=f"{trigger} (심각도={severity:.2f})",
            triggered_at=now,
        )

    async def _publish_emergency(self, trigger: str) -> None:
        """긴급 청산 이벤트를 발행한다."""
        try:
            from pydantic import BaseModel as _BM

            class _Payload(_BM):
                trigger: str

            await self._event_bus.publish(
                EventType.EMERGENCY_LIQUIDATION,
                _Payload(trigger=trigger),
            )
        except Exception:
            _logger.exception("긴급 이벤트 발행 실패")
