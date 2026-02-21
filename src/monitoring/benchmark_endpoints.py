"""
Flutter 대시보드용 벤치마크 비교 및 수익 목표 API 엔드포인트.

AI 전략 수익률과 SPY/SSO 벤치마크를 비교하고, 월간/일간 수익 목표 설정,
공격성 수준 조정, 수익 목표 이력 및 예측 데이터를 제공한다.

엔드포인트 목록:
  GET  /benchmark/comparison      - AI 전략 vs 벤치마크 비교 데이터
  GET  /benchmark/chart           - 벤치마크 비교 차트 데이터 (BenchmarkSnapshot)
  GET  /api/target/current        - 현재 수익 목표 상태 및 컨텍스트
  PUT  /api/target/monthly        - 월간 수익 목표 업데이트
  PUT  /api/target/aggression     - 공격성 수준 수동 설정
  GET  /api/target/history        - 과거 월간 목표/달성 이력
  GET  /api/target/projection     - 현재 추세 기반 월말 예상 수익
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select

from src.db.connection import get_session
from src.monitoring.auth import verify_api_key
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_benchmark_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}


def set_benchmark_deps(
    benchmark_comparison: Any = None,
    profit_target_manager: Any = None,
) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        benchmark_comparison: 벤치마크 비교 관리 인스턴스.
        profit_target_manager: 수익 목표 관리 인스턴스.
    """
    _deps["benchmark_comparison"] = benchmark_comparison
    _deps["profit_target_manager"] = profit_target_manager


def _get(name: str) -> Any:
    """의존성을 조회한다. 없으면 503을 반환한다.

    Args:
        name: 의존성 이름.

    Returns:
        의존성 인스턴스.

    Raises:
        HTTPException: 해당 의존성이 초기화되지 않은 경우 503을 반환한다.
    """
    dep = _deps.get(name)
    if dep is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{name}' is not available",
        )
    return dep


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다 (503 대신).

    Args:
        name: 의존성 이름.

    Returns:
        의존성 인스턴스 또는 None.
    """
    return _deps.get(name)


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

benchmark_router = APIRouter(tags=["benchmark"])


# ---------------------------------------------------------------------------
# GET /benchmark/comparison
# ---------------------------------------------------------------------------


@benchmark_router.get("/benchmark/comparison")
async def get_benchmark_comparison(
    period: str = Query(default="weekly", pattern="^(daily|weekly)$"),
    lookback: int = Query(default=4, ge=1, le=52),
) -> dict:
    """AI 전략 vs 벤치마크(SPY, SSO) 비교 데이터를 반환한다.

    benchmark_comparison 이 초기화되지 않은 경우 빈 데이터를 반환한다.

    Args:
        period: 비교 주기. "daily" 또는 "weekly" (기본 "weekly").
        lookback: 조회 기간 (기본 4, 최대 52).

    Returns:
        period, lookback, data 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 500: 내부 처리 오류.
    """
    bc = _try_get("benchmark_comparison")
    if bc is None:
        return {"period": period, "lookback": lookback, "data": []}
    try:
        comparison = await bc.get_comparison(period=period, lookback=lookback)
        return comparison
    except Exception as exc:
        logger.error("Failed to get benchmark comparison: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# GET /benchmark/chart
# ---------------------------------------------------------------------------


@benchmark_router.get("/benchmark/chart")
async def get_benchmark_chart(
    days: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    """벤치마크 비교 차트 데이터를 반환한다.

    benchmark_snapshots 테이블에서 일간 타입 레코드를 조회하여
    AI 전략과 SPY/SSO 패시브 바이앤홀드 수익률을 비교한다.

    Args:
        days: 조회 기간 (기본 30일, 최대 365일).

    Returns:
        date, ai_return_pct, spy_return_pct, sso_return_pct,
        ai_vs_spy_diff, ai_vs_sso_diff 키를 포함하는 딕셔너리 리스트.

    Raises:
        HTTPException 500: DB 조회 중 내부 오류.
    """
    try:
        from src.db.models import BenchmarkSnapshot

        async with get_session() as session:
            since = datetime.now(tz=timezone.utc) - timedelta(days=days)
            stmt = (
                select(BenchmarkSnapshot)
                .where(
                    and_(
                        BenchmarkSnapshot.period_type == "daily",
                        BenchmarkSnapshot.date >= since.date(),
                    )
                )
                .order_by(BenchmarkSnapshot.date.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "date": str(row.date),
                    "ai_return_pct": row.ai_return_pct,
                    "spy_return_pct": row.spy_buyhold_return_pct,
                    "sso_return_pct": row.sso_buyhold_return_pct,
                    "ai_vs_spy_diff": row.ai_vs_spy_diff,
                    "ai_vs_sso_diff": row.ai_vs_sso_diff,
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get benchmark chart: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# GET /api/target/current
# ---------------------------------------------------------------------------


@benchmark_router.get("/api/target/current")
async def get_target_current() -> dict:
    """현재 수익 목표 상태와 컨텍스트를 반환한다.

    profit_target_manager 가 초기화되지 않은 경우 기본값을 반환한다.

    Returns:
        monthly_target_usd, daily_target_usd, current_monthly_pnl,
        progress_pct, days_remaining, aggression_level, on_track 키를
        포함하는 딕셔너리.

    Raises:
        HTTPException 500: 내부 처리 오류.
    """
    ptm = _try_get("profit_target_manager")
    if ptm is None:
        return {
            "monthly_target_usd": 0.0,
            "daily_target_usd": 0.0,
            "current_monthly_pnl": 0.0,
            "progress_pct": 0.0,
            "days_remaining": 0,
            "aggression_level": "moderate",
            "on_track": False,
        }
    try:
        context = await ptm.get_context()
        return context
    except Exception as exc:
        logger.error("Failed to get target current: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# PUT /api/target/monthly
# ---------------------------------------------------------------------------


@benchmark_router.put("/api/target/monthly")
async def update_target_monthly(
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """월간 수익 목표를 업데이트한다.

    Args:
        body: monthly_target_usd (필수), daily_target_usd (선택) 키를
              포함하는 딕셔너리.

    Returns:
        업데이트된 수익 목표 정보 딕셔너리.

    Raises:
        HTTPException 400: monthly_target_usd 가 누락된 경우.
        HTTPException 422: 잘못된 금액 형식인 경우.
        HTTPException 500: 내부 처리 오류.
        HTTPException 503: profit_target_manager 가 초기화되지 않은 경우.
    """
    ptm = _get("profit_target_manager")
    try:
        monthly = body.get("monthly_target_usd")
        daily = body.get("daily_target_usd")
        if monthly is None:
            raise HTTPException(
                status_code=400, detail="monthly_target_usd is required"
            )
        try:
            monthly_float = float(monthly)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422, detail="잘못된 목표 금액 형식입니다."
            ) from exc
        try:
            daily_float = float(daily) if daily is not None else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422, detail="잘못된 일간 목표 금액 형식입니다."
            ) from exc
        result = await ptm.update_monthly_target(
            monthly_target_usd=monthly_float,
            daily_target_usd=daily_float,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update monthly target: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# PUT /api/target/aggression
# ---------------------------------------------------------------------------


@benchmark_router.put("/api/target/aggression")
async def update_target_aggression(
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """공격성 수준을 수동 설정한다.

    Args:
        body: aggression_level (선택), auto_adjust (선택) 키를 포함하는 딕셔너리.
              aggression_level 유효값: AggressionLevel enum 값.

    Returns:
        status, aggression_level, auto_adjust, params 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 400: 유효하지 않은 aggression_level 값인 경우.
        HTTPException 500: 내부 처리 오류.
        HTTPException 503: profit_target_manager 가 초기화되지 않은 경우.
    """
    ptm = _get("profit_target_manager")
    try:
        from src.strategy.profit_target import AggressionLevel

        level_str = body.get("aggression_level")
        auto_adjust = body.get("auto_adjust")

        if level_str is not None:
            try:
                level = AggressionLevel(level_str)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid aggression level: {level_str}. "
                    f"Valid: {[e.value for e in AggressionLevel]}",
                )
            ptm.config.aggression_level = level

        if auto_adjust is not None:
            ptm.config.auto_adjust = bool(auto_adjust)

        return {
            "status": "updated",
            "aggression_level": ptm.config.aggression_level.value,
            "auto_adjust": ptm.config.auto_adjust,
            "params": ptm.get_aggression_params(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update aggression: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# GET /api/target/history
# ---------------------------------------------------------------------------


@benchmark_router.get("/api/target/history")
async def get_target_history(
    months: int = Query(default=6, ge=1, le=24),
) -> list[dict]:
    """과거 월간 목표/달성 이력을 반환한다.

    Args:
        months: 조회할 이력 개월 수 (기본 6, 최대 24).

    Returns:
        월별 목표/달성 데이터 딕셔너리 리스트.

    Raises:
        HTTPException 500: 내부 처리 오류.
        HTTPException 503: profit_target_manager 가 초기화되지 않은 경우.
    """
    ptm = _get("profit_target_manager")
    try:
        history = await ptm.get_target_history(months=months)
        return history
    except Exception as exc:
        logger.error("Failed to get target history: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# GET /api/target/projection
# ---------------------------------------------------------------------------


@benchmark_router.get("/api/target/projection")
async def get_target_projection() -> dict:
    """현재 추세 기반 월말 예상 수익을 반환한다.

    Returns:
        월말 예상 수익 정보를 포함하는 딕셔너리.

    Raises:
        HTTPException 500: 내부 처리 오류.
        HTTPException 503: profit_target_manager 가 초기화되지 않은 경우.
    """
    ptm = _get("profit_target_manager")
    try:
        projection = await ptm.get_projection()
        return projection
    except Exception as exc:
        logger.error("Failed to get target projection: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")
