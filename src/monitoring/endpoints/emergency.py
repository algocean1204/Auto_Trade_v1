"""F7.9 EmergencyEndpoints -- 긴급 정지/재개 API이다.

긴급 상황 시 즉시 매매를 중단하고, 상태를 확인/재개할 수 있다.
모든 변경 엔드포인트는 Bearer 인증을 요구한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

emergency_router = APIRouter(prefix="/api/emergency", tags=["emergency"])

_system: InjectedSystem | None = None

# 긴급 정지 상태를 모듈 레벨에서 관리한다
_emergency_active: bool = False
_emergency_reason: str = ""


class EmergencyStatusResponse(BaseModel):
    """긴급 정지 상태 응답 모델이다."""

    emergency_active: bool
    reason: str
    system_running: bool


class EmergencyActionResponse(BaseModel):
    """긴급 정지/해제 응답 모델이다."""

    status: str
    reason: str | None = None
    previous_reason: str | None = None


def set_emergency_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("EmergencyEndpoints 의존성 주입 완료")


@emergency_router.get("/status", response_model=EmergencyStatusResponse)
async def get_emergency_status() -> EmergencyStatusResponse:
    """긴급 정지 상태를 반환한다."""
    return EmergencyStatusResponse(
        emergency_active=_emergency_active,
        reason=_emergency_reason,
        system_running=_system.running if _system else False,
    )


@emergency_router.post("/stop", response_model=EmergencyActionResponse)
async def emergency_stop(
    reason: str = "수동 긴급 정지",
    _key: str = Depends(verify_api_key),
) -> EmergencyActionResponse:
    """긴급 정지를 실행한다. 모든 매매를 즉시 중단한다."""
    global _emergency_active, _emergency_reason
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        _emergency_active = True
        _emergency_reason = reason
        _system.running = False

        # 이벤트 버스로 긴급 정지 알림을 전파한다
        event_bus = _system.components.event_bus
        await event_bus.emit("emergency_stop", {"reason": reason})

        _logger.warning("긴급 정지 실행: %s", reason)
        return EmergencyActionResponse(status="emergency_stopped", reason=reason)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("긴급 정지 실행 실패")
        raise HTTPException(status_code=500, detail="긴급 정지 실패") from None


@emergency_router.post("/resume", response_model=EmergencyActionResponse)
async def emergency_resume(
    _key: str = Depends(verify_api_key),
) -> EmergencyActionResponse:
    """긴급 정지를 해제한다. 매매 재개는 별도 start가 필요하다."""
    global _emergency_active, _emergency_reason
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        _emergency_active = False
        prev_reason = _emergency_reason
        _emergency_reason = ""

        event_bus = _system.components.event_bus
        await event_bus.emit("emergency_resume", {"prev_reason": prev_reason})

        _logger.info("긴급 정지 해제 완료 (이전 사유: %s)", prev_reason)
        return EmergencyActionResponse(
            status="resumed", previous_reason=prev_reason
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("긴급 정지 해제 실패")
        raise HTTPException(status_code=500, detail="해제 실패") from None
