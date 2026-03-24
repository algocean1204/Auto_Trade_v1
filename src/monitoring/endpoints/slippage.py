"""SlippageEndpoints -- 슬리피지 통계 조회 API이다.

평균 슬리피지, 최적 거래 시간대, 시간대별 슬리피지 통계를 제공한다.
SlippageTracker 인스턴스 또는 캐시에서 데이터를 읽는다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from src.monitoring.server.auth import verify_api_key
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

slippage_router = APIRouter(prefix="/api/slippage", tags=["slippage"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None


def set_slippage_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("SlippageEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 응답 모델 정의
# ---------------------------------------------------------------------------

class SlippageStatsResponse(BaseModel):
    """슬리피지 통계 응답이다. Flutter SlippageStats.fromJson 호환."""

    avg_slippage_pct: float
    """평균 슬리피지(%)이다."""
    total_slippage_cost: float
    """누적 슬리피지 금액(USD)이다."""
    max_slippage_pct: float
    """최대 슬리피지(%)이다."""
    best_execution_hour: int
    """체결 효율이 가장 좋은 시간(ET, 0-23)이다."""
    total_trades: int
    """통계 샘플 수(총 거래 수)이다."""
    median_slippage_pct: float = 0.0
    """중위 슬리피지(%)이다."""
    by_hour: dict = Field(default_factory=dict)
    """시간대별 슬리피지 통계이다."""


class SlippageHourEntry(BaseModel):
    """시간대별 슬리피지 항목이다."""

    hour: int
    """ET 기준 시각(0-23)이다."""
    avg_slippage: float
    """해당 시간대 평균 슬리피지(%)이다."""
    trade_count: int
    """해당 시간대 거래 수이다."""
    recommendation: str
    """체결 추천 수준이다 (EXCELLENT / GOOD / FAIR / AVOID)."""


class SlippageOptimalHoursResponse(BaseModel):
    """시간대별 슬리피지 최적 시간 응답이다."""

    hours: list[SlippageHourEntry] = Field(default_factory=list)
    """시간대별 슬리피지 목록이다."""


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _classify_hour_recommendation(avg_pct: float) -> str:
    """평균 슬리피지 기준으로 체결 추천 등급을 반환한다.

    슬리피지가 낮을수록(절댓값 기준) 좋은 체결 시간대이다.
    """
    abs_pct = abs(avg_pct)
    if abs_pct < 0.02:
        return "EXCELLENT"
    if abs_pct < 0.05:
        return "GOOD"
    if abs_pct < 0.10:
        return "FAIR"
    return "AVOID"


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

@slippage_router.get("/stats", response_model=SlippageStatsResponse)
async def get_slippage_stats(_auth: str = Depends(verify_api_key)) -> SlippageStatsResponse:
    """슬리피지 종합 통계를 반환한다.

    SlippageTracker가 features에 있으면 실시간 데이터를 사용한다.
    없으면 캐시 키 slippage:stats에서 읽는다.
    캐시 미스 시 기본값(0)으로 응답한다.
    """
    if _system is None:
        return SlippageStatsResponse(
            avg_slippage_pct=0.0,
            total_slippage_cost=0.0,
            max_slippage_pct=0.0,
            best_execution_hour=10,
            total_trades=0,
        )
    try:
        # SlippageTracker 직접 조회 (인메모리 데이터 우선)
        tracker = _system.features.get("slippage_tracker")
        if tracker is not None:
            avg_pct = tracker.get_average_pct()
            total_usd = tracker.get_total_amount()
            all_records = getattr(tracker, "_records", [])
            total_count = len(all_records)
            # 최대 슬리피지 계산 시 최근 500건만 순회하여 대량 데이터 방지한다
            _MAX_SLIPPAGE_SCAN = 500
            recent_records = all_records[-_MAX_SLIPPAGE_SCAN:] if len(all_records) > _MAX_SLIPPAGE_SCAN else all_records
            worst = max(
                (abs(r.slippage_pct) for r in recent_records),
                default=0.0,
            )
            # best_execution_hour: 집계 캐시에서 읽는다 (EOD aggregator가 산출)
            best_hour = 10
            try:
                cache = _system.components.cache
                cached_stats = await cache.read_json("slippage:stats")
                if cached_stats and isinstance(cached_stats, dict):
                    best_hour = int(cached_stats.get("best_execution_hour", 10))
            except Exception:
                pass
            return SlippageStatsResponse(
                avg_slippage_pct=avg_pct,
                total_slippage_cost=total_usd,
                max_slippage_pct=worst,
                best_execution_hour=best_hour,
                total_trades=total_count,
            )

        # 캐시에서 읽는다
        cache = _system.components.cache
        cached = await cache.read_json("slippage:stats")
        if cached and isinstance(cached, dict):
            return SlippageStatsResponse(
                avg_slippage_pct=float(cached.get("avg_slippage_pct", 0.0)),
                total_slippage_cost=float(cached.get("total_slippage_cost", cached.get("total_slippage_usd", 0.0))),
                max_slippage_pct=float(cached.get("max_slippage_pct", cached.get("worst_slippage", 0.0))),
                best_execution_hour=int(cached.get("best_execution_hour", 10)),
                total_trades=int(cached.get("total_trades", cached.get("sample_size", 0))),
                median_slippage_pct=float(cached.get("median_slippage_pct", 0.0)),
                by_hour=cached.get("by_hour", {}),
            )

        return SlippageStatsResponse(
            avg_slippage_pct=0.0,
            total_slippage_cost=0.0,
            max_slippage_pct=0.0,
            best_execution_hour=10,
            total_trades=0,
        )
    except Exception:
        _logger.exception("슬리피지 통계 조회 실패")
        raise HTTPException(status_code=500, detail="슬리피지 통계 조회 중 오류가 발생했다") from None


@slippage_router.get("/optimal-hours", response_model=SlippageOptimalHoursResponse)
async def get_optimal_hours(
    ticker: str | None = None,
    _auth: str = Depends(verify_api_key),
) -> SlippageOptimalHoursResponse:
    """시간대별 슬리피지 통계 및 최적 체결 시간을 반환한다.

    ticker 파라미터가 있으면 해당 티커 전용 캐시를 우선 조회한다.
    캐시 미스 시 전체 통계(slippage:hours)를 반환한다.
    """
    if _system is None:
        return SlippageOptimalHoursResponse(hours=[])
    try:
        cache = _system.components.cache
        # 티커별 캐시를 우선 조회한다 (향후 티커별 데이터 저장 시 활용)
        cached = None
        if ticker:
            cached = await cache.read_json(f"slippage:hours:{ticker}")
        if not cached:
            cached = await cache.read_json("slippage:hours")
        if cached and isinstance(cached, list):
            hours = [
                SlippageHourEntry(
                    hour=int(h.get("hour", 0)),
                    avg_slippage=float(h.get("avg_slippage", 0.0)),
                    trade_count=int(h.get("trade_count", 0)),
                    recommendation=str(
                        h.get(
                            "recommendation",
                            _classify_hour_recommendation(float(h.get("avg_slippage", 0.0))),
                        )
                    ),
                )
                for h in cached
            ]
            return SlippageOptimalHoursResponse(hours=hours)
        return SlippageOptimalHoursResponse(hours=[])
    except Exception:
        _logger.exception("최적 체결 시간대 조회 실패")
        raise HTTPException(status_code=500, detail="최적 체결 시간대 조회 중 오류가 발생했다") from None
