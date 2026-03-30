"""F7.28 HealingEndpoints -- Self-Healing 상태 조회 및 수동 트리거 API이다.

에러 모니터링봇과 매매 감시봇의 상태를 조회하고,
수동으로 수리를 트리거할 수 있는 엔드포인트를 제공한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

healing_router = APIRouter(
    prefix="/api/healing",
    tags=["healing"],
)

_system: InjectedSystem | None = None


def set_healing_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("HealingEndpoints 의존성 주입 완료")


class HealingStatusResponse(BaseModel):
    """Self-Healing 상태 응답이다."""

    monitor_running: bool = Field(description="에러 모니터링봇 실행 여부")
    watchdog_running: bool = Field(description="매매 감시봇 실행 여부")
    total_errors: int = Field(description="누적 에러 수")
    total_repairs: int = Field(description="누적 수리 성공 수")
    pending_errors: int = Field(description="대기 중 에러 수")
    trade_detected: bool = Field(description="당일 매매 감지 여부")
    relaxation_level: int = Field(description="현재 임계값 완화 레벨 (0=없음)")
    circuit_breakers: dict[str, int] = Field(
        default_factory=dict, description="서킷 브레이커 발동 현황",
    )
    budget_summary: dict[str, object] = Field(
        default_factory=dict, description="API 예산 사용 현황",
    )
    cache_summary: dict[str, object] = Field(
        default_factory=dict, description="수리 학습 캐시 현황",
    )


class RepairTriggerResponse(BaseModel):
    """수동 수리 트리거 응답이다."""

    triggered: bool = Field(description="수리 트리거 성공 여부")
    detail: str = Field(description="수리 결과 상세")


@healing_router.get(
    "/status",
    response_model=HealingStatusResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_healing_status() -> HealingStatusResponse:
    """Self-Healing 시스템의 현재 상태를 반환한다."""
    assert _system is not None
    monitor = _system.features.get("error_monitor")
    watchdog = _system.features.get("trade_watchdog")

    monitor_status = monitor.get_status() if monitor else {}
    watchdog_status = watchdog.get_status() if watchdog else {}
    repair_mgr = monitor_status.get("repair_manager", {}) if monitor_status else {}

    return HealingStatusResponse(
        monitor_running=monitor_status.get("running", False),
        watchdog_running=watchdog_status.get("running", False),
        total_errors=monitor_status.get("total_errors", 0),
        total_repairs=monitor_status.get("total_repairs", 0),
        pending_errors=monitor_status.get("pending_errors", 0),
        trade_detected=watchdog_status.get("trade_detected", False),
        relaxation_level=watchdog_status.get("relaxation_level", 0),
        circuit_breakers=repair_mgr.get("circuit_breakers", {}),
        budget_summary=repair_mgr.get("budget", {}),
        cache_summary=repair_mgr.get("cache", {}),
    )


@healing_router.post(
    "/review",
    response_model=RepairTriggerResponse,
    dependencies=[Depends(verify_api_key)],
)
async def trigger_error_review() -> RepairTriggerResponse:
    """수집된 에러를 즉시 검토하고 수리를 시도한다."""
    assert _system is not None
    monitor = _system.features.get("error_monitor")
    if monitor is None:
        return RepairTriggerResponse(triggered=False, detail="에러 모니터링봇 미등록")

    count = await monitor.manual_review()
    if count == 0:
        return RepairTriggerResponse(triggered=True, detail="대기 중 에러 없음")

    return RepairTriggerResponse(triggered=True, detail=f"{count}건 에러 검토 완료")


@healing_router.post(
    "/reset",
    response_model=RepairTriggerResponse,
    dependencies=[Depends(verify_api_key)],
)
async def reset_healing_session() -> RepairTriggerResponse:
    """Self-Healing 세션을 초기화한다. 서킷 브레이커와 예산을 리셋한다."""
    assert _system is not None
    monitor = _system.features.get("error_monitor")
    if monitor is None:
        return RepairTriggerResponse(triggered=False, detail="에러 모니터링봇 미등록")

    monitor.reset_session()
    return RepairTriggerResponse(triggered=True, detail="세션 초기화 완료")
