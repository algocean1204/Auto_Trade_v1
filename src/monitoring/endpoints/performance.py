"""F7.17 PerformanceEndpoints -- 성과 조회 API이다.

성과 요약, 일별/월별 성과 데이터를 제공한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

performance_router = APIRouter(prefix="/api/performance", tags=["performance"])

_system: InjectedSystem | None = None


class PerformanceSummaryResponse(BaseModel):
    """성과 요약 응답 모델이다."""

    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    today_pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    message: str = ""


class DailyPerformanceResponse(BaseModel):
    """일별 성과 응답 모델이다."""

    daily: list[dict[str, Any]] = Field(default_factory=list)


class MonthlyPerformanceResponse(BaseModel):
    """월별 성과 응답 모델이다."""

    monthly: list[dict[str, Any]] = Field(default_factory=list)


def set_performance_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("PerformanceEndpoints 의존성 주입 완료")


@performance_router.get("/summary", response_model=PerformanceSummaryResponse)
async def get_performance_summary() -> PerformanceSummaryResponse:
    """성과 요약을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("performance:summary")
        if cached and isinstance(cached, dict):
            return PerformanceSummaryResponse(
                total_pnl=cached.get("total_pnl", 0.0),
                total_pnl_pct=cached.get("total_pnl_pct", 0.0),
                today_pnl=cached.get("today_pnl", 0.0),
                win_rate=cached.get("win_rate", 0.0),
                total_trades=cached.get("total_trades", 0),
                sharpe_ratio=cached.get("sharpe_ratio", 0.0),
                max_drawdown=cached.get("max_drawdown", 0.0),
                message=cached.get("message", ""),
            )
        return PerformanceSummaryResponse(message="성과 데이터가 없다")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("성과 요약 조회 실패")
        raise HTTPException(status_code=500, detail="성과 조회 실패") from None


@performance_router.get("/daily", response_model=DailyPerformanceResponse)
async def get_daily_performance(
    limit: int = 30,
) -> DailyPerformanceResponse:
    """일별 성과를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("performance:daily")
        data = cached if isinstance(cached, list) else []
        return DailyPerformanceResponse(daily=data[:limit])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 성과 조회 실패")
        raise HTTPException(status_code=500, detail="일별 성과 조회 실패") from None


@performance_router.get("/monthly", response_model=MonthlyPerformanceResponse)
async def get_monthly_performance(
    limit: int = 12,
) -> MonthlyPerformanceResponse:
    """월별 성과를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("performance:monthly")
        data = cached if isinstance(cached, list) else []
        return MonthlyPerformanceResponse(monthly=data[:limit])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("월별 성과 조회 실패")
        raise HTTPException(status_code=500, detail="월별 성과 조회 실패") from None
