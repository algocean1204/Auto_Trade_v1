"""F7.17 PerformanceEndpoints -- 성과 조회 API이다.

성과 요약, 일별/월별 성과 데이터를 제공한다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.monitoring.server.auth import verify_api_key
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
    """DB daily_pnl_log + feedback_reports에서 성과 요약을 생성한다.

    조회 결과를 캐시에 저장하여 반복 DB 쿼리를 방지한다.
    """
    if _system is None:
        return None
    try:
        db = _system.components.db
        # 최대 365일분 PnL + 365건 피드백으로 제한하여 OOM을 방지한다
        _MAX_PNL_ROWS = 365
        _MAX_REPORT_ROWS = 365
        async with db.get_session() as session:
            # daily_pnl_log에서 총 PnL/수익률 계산 (최근 365일 제한)
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.desc())
                .limit(_MAX_PNL_ROWS)
            )
            result = await session.execute(stmt)
            pnl_rows = result.scalars().all()

            # feedback_reports에서 거래 통계 계산 (최근 365건 제한)
            stmt2 = (
                select(FeedbackReport)
                .order_by(FeedbackReport.report_date.desc())
                .limit(_MAX_REPORT_ROWS)
            )
            result2 = await session.execute(stmt2)
            reports = result2.scalars().all()

            if not pnl_rows and not reports:
                return None

            # ORM 속성은 세션 컨텍스트 내에서 접근해야 DetachedInstanceError를 방지한다
            total_pnl = sum(r.pnl_amount or 0 for r in pnl_rows)
            total_pnl_pct = sum(r.pnl_pct or 0 for r in pnl_rows)
            today_pnl = (pnl_rows[0].pnl_amount or 0.0) if pnl_rows else 0.0

            # 피드백 리포트에서 거래 수/승률 합산
            total_trades = 0
            wins = 0
            for report in reports:
                content = report.content
                if isinstance(content, str):
                    content = json.loads(content)
                if isinstance(content, dict):
                    summary = content.get("summary", {})
                    trades_n = summary.get("total_trades", 0)
                    total_trades += trades_n
                    # AI 피드백은 winning_trades가 아닌 win_rate를 제공한다
                    explicit_wins = summary.get("winning_trades", 0)
                    if explicit_wins > 0:
                        wins += explicit_wins
                    elif trades_n > 0:
                        wr = summary.get("win_rate", 0)
                        wins += round(wr / 100 * trades_n)

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        result_data = {
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "today_pnl": today_pnl,
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
            "message": "DB 기반 요약",
        }
        # DB 폴백 결과를 정식 캐시 키에 저장하여 반복 쿼리를 방지한다 (1시간 TTL)
        try:
            cache = _system.components.cache
            await cache.write_json("performance:summary", result_data, ttl=3600)
        except Exception:
            _logger.debug("성과 요약 캐시 저장 실패 (무시)")
        return result_data
    except Exception:
        _logger.warning("DB에서 성과 요약 생성 실패")
        return None


async def _build_daily_from_db(limit: int) -> list[dict[str, Any]]:
    """DB daily_pnl_log에서 일별 성과 목록을 생성한다.

    조회 결과를 캐시에 저장하여 반복 DB 쿼리를 방지한다.
    항상 최대 365일치를 조회하여 캐시에 저장하고, limit으로 슬라이싱한다.
    """
    if _system is None:
        return []
    try:
        db = _system.components.db
        # 항상 최대 365일을 조회하여 캐시에 저장한다 (이후 다른 limit 요청에도 대응)
        _MAX_ROWS = 365
        async with db.get_session() as session:
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.desc())
                .limit(_MAX_ROWS)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            # ORM 속성은 세션 컨텍스트 내에서 접근해야 DetachedInstanceError를 방지한다
            daily_data = [
                {
                    "date": r.date,
                    "pnl": r.pnl_amount or 0.0,
                    "pnl_pct": r.pnl_pct or 0.0,
                    "equity": r.equity or 0.0,
                }
                for r in rows
            ]
        # DB 폴백 결과를 정식 캐시 키에 저장하여 반복 쿼리를 방지한다 (1시간 TTL)
        if daily_data:
            try:
                cache = _system.components.cache
                await cache.write_json("performance:daily", daily_data, ttl=3600)
            except Exception:
                _logger.debug("일별 성과 캐시 저장 실패 (무시)")
        # 요청된 limit만큼 슬라이싱하여 반환한다
        return daily_data[:limit]
    except Exception:
        _logger.warning("DB에서 일별 성과 조회 실패")
        return []


async def _build_monthly_from_db(limit: int) -> list[dict[str, Any]]:
    """DB daily_pnl_log에서 월별 집계 성과를 생성한다.

    일별 PnL을 월 단위로 그룹핑하여 합산한다.
    조회 결과를 캐시에 저장하여 반복 DB 쿼리를 방지한다.
    """
    if _system is None:
        return []
    try:
        db = _system.components.db
        # 최근 365일 × limit개월을 커버하기에 충분한 행을 가져온다
        _MAX_ROWS = 365
        async with db.get_session() as session:
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.desc())
                .limit(_MAX_ROWS)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                return []

            # ORM 속성은 세션 컨텍스트 내에서 접근해야 DetachedInstanceError를 방지한다
            monthly_pnl: defaultdict[str, float] = defaultdict(float)
            monthly_pnl_pct: defaultdict[str, float] = defaultdict(float)
            monthly_trades: defaultdict[str, int] = defaultdict(int)

            for r in rows:
                date_str = str(r.date) if r.date else ""
                if len(date_str) < 7:
                    continue
                month_key = date_str[:7]  # "YYYY-MM"
                monthly_pnl[month_key] += r.pnl_amount or 0.0
                monthly_pnl_pct[month_key] += r.pnl_pct or 0.0
                monthly_trades[month_key] += 1

        # 최신 월 순으로 정렬하여 limit개 반환한다
        sorted_months = sorted(monthly_pnl.keys(), reverse=True)[:limit]
        monthly_data = [
            {
                "month": m,
                "pnl": round(monthly_pnl[m], 2),
                "pnl_pct": round(monthly_pnl_pct[m], 4),
                "trading_days": monthly_trades[m],
            }
            for m in sorted_months
        ]

        # DB 폴백 결과를 정식 캐시 키에 저장하여 반복 쿼리를 방지한다 (1시간 TTL)
        if monthly_data:
            try:
                cache = _system.components.cache
                await cache.write_json("performance:monthly", monthly_data, ttl=3600)
            except Exception:
                _logger.debug("월별 성과 캐시 저장 실패 (무시)")
        return monthly_data
    except Exception:
        _logger.warning("DB에서 월별 성과 조회 실패")
        return []


@performance_router.get("/summary", response_model=PerformanceSummaryResponse)
async def get_performance_summary(_auth: str = Depends(verify_api_key)) -> PerformanceSummaryResponse:
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
    limit: int = Query(default=30, ge=1, le=365),
    _auth: str = Depends(verify_api_key),
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
    limit: int = Query(default=12, ge=1, le=120),
    _auth: str = Depends(verify_api_key),
) -> MonthlyPerformanceResponse:
    """월별 성과를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("performance:monthly")
        data = cached if isinstance(cached, list) else []
        if data:
            return MonthlyPerformanceResponse(monthly=data[:limit])
        # 캐시 미스 시 DB fallback: daily_pnl_log를 월별로 집계한다
        db_monthly = await _build_monthly_from_db(limit)
        return MonthlyPerformanceResponse(monthly=db_monthly)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("월별 성과 조회 실패")
        raise HTTPException(status_code=500, detail="월별 성과 조회 실패") from None
