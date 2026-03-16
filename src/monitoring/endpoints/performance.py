"""F7.17 PerformanceEndpoints -- 성과 조회 API이다.

성과 요약, 일별/월별 성과 데이터를 제공한다.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.common.logger import get_logger
from src.db.models import DailyPnlLog, FeedbackReport

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


async def _build_summary_from_db() -> dict[str, Any] | None:
    """DB daily_pnl_log + feedback_reports에서 성과 요약을 생성한다."""
    if _system is None:
        return None
    try:
        db = _system.components.db
        async with db.get_session() as session:
            # daily_pnl_log에서 총 PnL/수익률 계산
            stmt = select(DailyPnlLog).order_by(DailyPnlLog.date.desc())
            result = await session.execute(stmt)
            pnl_rows = result.scalars().all()

            # feedback_reports에서 거래 통계 계산
            stmt2 = select(FeedbackReport).order_by(
                FeedbackReport.report_date.desc()
            )
            result2 = await session.execute(stmt2)
            reports = result2.scalars().all()

        if not pnl_rows and not reports:
            return None

        total_pnl = sum(r.pnl_amount or 0 for r in pnl_rows)
        total_pnl_pct = sum(r.pnl_pct or 0 for r in pnl_rows)

        # 피드백 리포트에서 거래 수/승률 합산
        total_trades = 0
        wins = 0
        for report in reports:
            content = report.content
            if isinstance(content, str):
                content = json.loads(content)
            if isinstance(content, dict):
                summary = content.get("summary", {})
                total_trades += summary.get("total_trades", 0)
                wins += summary.get("winning_trades", 0)

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        return {
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "today_pnl": pnl_rows[0].pnl_amount if pnl_rows else 0.0,
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
            "message": "DB 기반 요약",
        }
    except Exception:
        _logger.warning("DB에서 성과 요약 생성 실패")
        return None


async def _build_daily_from_db(limit: int) -> list[dict[str, Any]]:
    """DB daily_pnl_log에서 일별 성과 목록을 생성한다."""
    if _system is None:
        return []
    try:
        db = _system.components.db
        async with db.get_session() as session:
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [
            {
                "date": r.date,
                "pnl": r.pnl_amount or 0.0,
                "pnl_pct": r.pnl_pct or 0.0,
                "equity": r.equity or 0.0,
            }
            for r in rows
        ]
    except Exception:
        _logger.warning("DB에서 일별 성과 조회 실패")
        return []


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
        # 캐시 미스 시 DB fallback
        db_summary = await _build_summary_from_db()
        if db_summary:
            return PerformanceSummaryResponse(**db_summary)
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
        if data:
            return DailyPerformanceResponse(daily=data[:limit])
        # 캐시 미스 시 DB fallback
        db_daily = await _build_daily_from_db(limit)
        return DailyPerformanceResponse(daily=db_daily)
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
