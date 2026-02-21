"""
Flutter 대시보드용 긴급 프로토콜 및 리스크 관리 API 엔드포인트.

긴급 정지/해제, 긴급 이벤트 이력, 리스크 게이트, VaR,
연패 상태, 리스크 대시보드, 리스크 백테스트 엔드포인트를 제공한다.

엔드포인트 목록:
  POST /emergency/stop                 - 긴급 정지 발동
  POST /emergency/resume               - 긴급 정지 해제
  GET  /emergency/status               - 긴급 프로토콜 상태
  GET  /emergency/history              - 긴급 이벤트 이력
  GET  /api/risk/status                - 리스크 게이트 현재 상태
  GET  /api/risk/gates                 - 전체 리스크 게이트 점검
  PUT  /api/risk/config                - 리스크 설정 업데이트
  GET  /api/risk/budget                - 리스크 예산 소비 현황
  GET  /api/risk/backtest              - 최신 백테스트 결과
  POST /api/risk/backtest/run          - 백테스트 실행
  GET  /api/risk/streak                - 연패 상태
  GET  /api/risk/var                   - VaR 상태
  GET  /api/risk/dashboard             - 리스크 대시보드 통합 데이터
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.db.connection import get_session
from src.db.models import EmergencyEvent
from src.monitoring.auth import verify_api_key
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_emergency_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}


def set_emergency_deps(
    emergency_protocol: Any = None,
    position_monitor: Any = None,
    risk_gate_pipeline: Any = None,
    risk_budget: Any = None,
    risk_backtester: Any = None,
) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        emergency_protocol: 긴급 프로토콜 인스턴스.
        position_monitor: 포지션 모니터 인스턴스.
        risk_gate_pipeline: 리스크 게이트 파이프라인 인스턴스.
        risk_budget: 리스크 예산 인스턴스.
        risk_backtester: 리스크 백테스터 인스턴스.
    """
    _deps.update({
        "emergency_protocol": emergency_protocol,
        "position_monitor": position_monitor,
        "risk_gate_pipeline": risk_gate_pipeline,
        "risk_budget": risk_budget,
        "risk_backtester": risk_backtester,
    })


def _get(name: str) -> Any:
    """의존성을 조회한다. 없으면 503을 반환한다."""
    dep = _deps.get(name)
    if dep is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{name}' is not available",
        )
    return dep


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다 (503 대신)."""
    return _deps.get(name)


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

emergency_router = APIRouter(tags=["emergency"])


# ===================================================================
# 요청 스키마
# ===================================================================


class EmergencyStopRequest(BaseModel):
    """긴급 정지 요청 스키마."""

    reason: str = "Manual"


# ===================================================================
# Emergency endpoints
# ===================================================================


@emergency_router.post("/emergency/stop")
async def emergency_stop(
    body: EmergencyStopRequest = EmergencyStopRequest(),
    _: None = Depends(verify_api_key),
) -> dict:
    """긴급 정지를 발동한다. 모든 매매를 중단하고 포지션 청산을 준비한다.

    Args:
        body: 긴급 정지 요청 본문. reason 필드에 정지 사유를 기록한다.
    """
    ep = _get("emergency_protocol")
    monitor = _try_get("position_monitor")
    logger.warning("긴급 정지 발동 요청: reason=%s", body.reason)
    try:
        positions = []
        if monitor is not None:
            portfolio = await monitor.get_portfolio_summary()
            positions = portfolio.get("positions", [])

        result = await ep.handle_runaway_loss(positions)
        logger.info("긴급 정지 완료: reason=%s, result=%s", body.reason, result)
        return {
            "status": "emergency_stop_activated",
            "reason": body.reason,
            "result": result,
        }
    except Exception as exc:
        logger.error("Emergency stop failed: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.post("/emergency/resume")
async def emergency_resume(_: None = Depends(verify_api_key)) -> dict:
    """긴급 정지를 해제하고 매매를 재개한다."""
    ep = _get("emergency_protocol")
    try:
        ep.is_runaway_loss_shutdown = False
        ep.is_circuit_breaker_active = False
        ep.reset_daily()
        return {
            "status": "resumed",
            "message": "긴급 정지 해제, 매매 재개",
        }
    except Exception as exc:
        logger.error("Emergency resume failed: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/emergency/status")
async def get_emergency_status() -> dict:
    """현재 긴급 프로토콜 상태를 반환한다."""
    ep = _try_get("emergency_protocol")
    if ep is None:
        return {
            "circuit_breaker_active": False,
            "runaway_loss_shutdown": False,
            "flash_crash_cooldowns": {},
        }
    try:
        return ep.get_status()
    except Exception as exc:
        logger.error("Failed to get emergency status: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/emergency/history")
async def get_emergency_history(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """긴급 이벤트 이력을 반환한다."""
    try:
        async with get_session() as session:
            stmt = (
                select(EmergencyEvent)
                .order_by(EmergencyEvent.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": str(row.id),
                    "event_type": row.event_type,
                    "trigger_value": row.trigger_value,
                    "action_taken": row.action_taken,
                    "positions_affected": row.positions_affected,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get emergency history: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ===================================================================
# Risk endpoints (Addendum 26)
# ===================================================================


@emergency_router.get("/api/risk/status")
async def get_risk_status() -> dict:
    """리스크 게이트 파이프라인의 현재 상태를 반환한다."""
    rgp = _get("risk_gate_pipeline")
    try:
        status = rgp.get_status()
        return status
    except Exception as exc:
        logger.error("Failed to get risk status: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/api/risk/gates")
async def get_risk_gates() -> dict:
    """전체 리스크 게이트 점검을 실행하고 결과를 반환한다."""
    rgp = _get("risk_gate_pipeline")
    monitor = _get("position_monitor")
    try:
        portfolio = await monitor.get_portfolio_summary()
        result = await rgp.check_all(portfolio)
        return {
            "can_trade": result.can_trade,
            "overall_action": result.overall_action,
            "blocking_gates": result.blocking_gates,
            "gates": [
                {
                    "gate_name": gr.gate_name,
                    "passed": gr.passed,
                    "action": gr.action,
                    "message": gr.message,
                    "details": gr.details,
                }
                for gr in result.gate_results
            ],
        }
    except Exception as exc:
        logger.error("Failed to run risk gates: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.put("/api/risk/config")
async def update_risk_config(
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """리스크 설정을 업데이트한다."""
    rgp = _get("risk_gate_pipeline")
    try:
        updated: dict[str, Any] = {}

        if rgp.concentration_limiter is not None:
            cl = rgp.concentration_limiter
            if "single_max_pct" in body:
                cl.single_max_pct = float(body["single_max_pct"])
                updated["single_max_pct"] = cl.single_max_pct
            if "total_max_pct" in body:
                cl.total_max_pct = float(body["total_max_pct"])
                updated["total_max_pct"] = cl.total_max_pct
            if "min_cash_pct" in body:
                cl.min_cash_pct = float(body["min_cash_pct"])
                updated["min_cash_pct"] = cl.min_cash_pct
            if "max_positions" in body:
                cl.max_positions = int(body["max_positions"])
                updated["max_positions"] = cl.max_positions

        if rgp.simple_var is not None:
            sv = rgp.simple_var
            if "max_var_pct" in body:
                sv.max_var_pct = float(body["max_var_pct"])
                updated["max_var_pct"] = sv.max_var_pct

        return {"status": "updated", "updated": updated}
    except Exception as exc:
        logger.error("Failed to update risk config: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/api/risk/budget")
async def get_risk_budget() -> dict:
    """현재 리스크 예산 소비 현황을 반환한다."""
    rb = _get("risk_budget")
    try:
        consumption = await rb.get_consumption()
        return consumption
    except Exception as exc:
        logger.error("Failed to get risk budget: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/api/risk/backtest")
async def get_risk_backtest() -> dict:
    """최신 리스크 백테스트 결과를 반환한다."""
    rbt = _get("risk_backtester")
    try:
        result = await rbt.get_latest_result()
        if result is None:
            return {"status": "no_data", "message": "백테스트 결과 없음"}
        return result
    except Exception as exc:
        logger.error("Failed to get risk backtest: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.post("/api/risk/backtest/run")
async def run_risk_backtest(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_api_key),
    body: dict | None = None,
) -> dict:
    """리스크 백테스트를 실행한다 (백그라운드)."""
    rbt = _get("risk_backtester")
    try:
        scenarios = body.get("scenarios") if body else None

        async def _run() -> None:
            try:
                await rbt.run_backtest(scenarios=scenarios)
            except Exception as e:
                logger.error("Background risk backtest failed: %s", e)

        background_tasks.add_task(_run)
        return {"status": "started", "message": "백테스트 백그라운드 실행 시작"}
    except Exception as exc:
        logger.error("Failed to start risk backtest: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/api/risk/streak")
async def get_risk_streak() -> dict:
    """현재 연패 상태를 반환한다."""
    rgp = _get("risk_gate_pipeline")
    try:
        if rgp.losing_streak_detector is None:
            raise HTTPException(
                status_code=503, detail="LosingStreakDetector not available"
            )
        return rgp.losing_streak_detector.get_status()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get risk streak: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/api/risk/var")
async def get_risk_var() -> dict:
    """현재 VaR 상태를 반환한다."""
    rgp = _get("risk_gate_pipeline")
    try:
        if rgp.simple_var is None:
            raise HTTPException(
                status_code=503, detail="SimpleVaR not available"
            )
        return rgp.simple_var.get_status()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get risk var: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@emergency_router.get("/api/risk/dashboard")
async def get_risk_dashboard() -> dict:
    """리스크 대시보드용 통합 데이터를 단일 응답으로 반환한다.

    Flutter 프론트엔드가 여러 리스크 엔드포인트를 개별 호출하는 대신
    이 엔드포인트 하나로 모든 리스크 데이터를 조회한다.

    각 서브 컴포넌트는 독립적인 try/except로 감싸져 있어,
    일부 컴포넌트 실패 시에도 나머지 데이터는 정상 반환된다.
    """
    rgp = _try_get("risk_gate_pipeline")
    rb = _try_get("risk_budget")
    monitor = _try_get("position_monitor")

    if rgp is None and rb is None and monitor is None:
        return {
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "gates": [],
            "risk_budget": {},
            "var_indicator": {},
            "streak_counter": {},
            "concentrations": {"limits": {}, "positions": []},
            "trailing_stop": {"active": False, "positions": []},
        }

    result: dict[str, Any] = {
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    cached_portfolio: dict[str, Any] = {}
    if monitor is not None:
        try:
            cached_portfolio = await monitor.get_portfolio_summary()
        except Exception as exc:
            logger.warning("risk/dashboard: 포트폴리오 조회 실패: %s", exc)

    # 1. 게이트 점검 결과
    try:
        pipeline_result = await rgp.check_all(cached_portfolio)
        result["gates"] = [
            {
                "gate_name": gr.gate_name,
                "passed": gr.passed,
                "action": gr.action,
                "message": gr.message,
                "details": gr.details,
            }
            for gr in pipeline_result.gate_results
        ]
    except Exception as exc:
        logger.warning("risk/dashboard: gates 집계 실패: %s", exc)
        result["gates"] = []

    # 2. 리스크 예산 소비 현황
    try:
        result["risk_budget"] = await rb.get_consumption()
    except Exception as exc:
        logger.warning("risk/dashboard: risk_budget 집계 실패: %s", exc)
        result["risk_budget"] = {}

    # 3. VaR 지표
    try:
        if rgp.simple_var is not None:
            result["var_indicator"] = rgp.simple_var.get_status()
        else:
            result["var_indicator"] = {}
    except Exception as exc:
        logger.warning("risk/dashboard: var_indicator 집계 실패: %s", exc)
        result["var_indicator"] = {}

    # 4. 연패 카운터
    try:
        if rgp.losing_streak_detector is not None:
            result["streak_counter"] = rgp.losing_streak_detector.get_status()
        else:
            result["streak_counter"] = {}
    except Exception as exc:
        logger.warning("risk/dashboard: streak_counter 집계 실패: %s", exc)
        result["streak_counter"] = {}

    # 5. 집중도 현황
    try:
        if rgp.concentration_limiter is not None:
            conc_status = rgp.concentration_limiter.get_status()
            positions = cached_portfolio.get("positions", [])
            total_value = cached_portfolio.get("total_value", 0.0)
            concentration_details: list[dict[str, Any]] = []
            if total_value > 0 and isinstance(positions, list):
                for pos in positions:
                    market_value = pos.get("market_value", 0.0)
                    concentration_details.append({
                        "ticker": pos.get("ticker", ""),
                        "market_value": market_value,
                        "weight_pct": round((market_value / total_value) * 100.0, 2),
                    })
            result["concentrations"] = {
                "limits": conc_status,
                "positions": concentration_details,
            }
        else:
            result["concentrations"] = {}
    except Exception as exc:
        logger.warning("risk/dashboard: concentrations 집계 실패: %s", exc)
        result["concentrations"] = {}

    # 6. 트레일링 스톱 현황
    try:
        if rgp.trailing_stop_loss is not None:
            result["trailing_stop"] = rgp.trailing_stop_loss.get_status()
        else:
            result["trailing_stop"] = {}
    except Exception as exc:
        logger.warning("risk/dashboard: trailing_stop 집계 실패: %s", exc)
        result["trailing_stop"] = {}

    return result
