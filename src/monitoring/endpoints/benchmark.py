"""F7.10 BenchmarkEndpoints -- 벤치마크 비교 API이다.

SPY/SSO 대비 AI 포트폴리오 수익률 비교 및 차트 데이터를 제공한다.
Flutter 프론트엔드 BenchmarkComparison / BenchmarkChartPoint 모델에 맞춰
periods(일별 비교 리스트) + summary(요약 통계) 구조로 반환한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

benchmark_router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_system: InjectedSystem | None = None

# 기간 매핑: 쿼리 파라미터 → 슬라이싱 일수
_PERIOD_DAYS: dict[str, int] = {
    "1W": 7,
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
}


# ---------------------------------------------------------------------------
# Pydantic 응답 모델 (Flutter BenchmarkComparison과 일치)
# ---------------------------------------------------------------------------

class BenchmarkPeriodItem(BaseModel):
    """일별 벤치마크 비교 항목이다."""

    date: str = ""
    ai_return_pct: float = 0.0
    spy_return_pct: float = 0.0
    sso_return_pct: float = 0.0
    ai_vs_spy_diff: float = 0.0
    ai_vs_sso_diff: float = 0.0


class BenchmarkSummaryItem(BaseModel):
    """벤치마크 비교 요약 통계이다."""

    ai_total: float = 0.0
    spy_total: float = 0.0
    sso_total: float = 0.0
    ai_win_rate_vs_spy: float = 0.0
    ai_win_rate_vs_sso: float = 0.0


class BenchmarkComparisonResponse(BaseModel):
    """벤치마크 비교 응답 모델이다.

    Flutter BenchmarkComparison.fromJson이 기대하는 구조:
      {"periods": [...], "summary": {...}}
    """

    periods: list[BenchmarkPeriodItem] = Field(default_factory=list)
    summary: BenchmarkSummaryItem = Field(default_factory=BenchmarkSummaryItem)


class BenchmarkChartResponse(BaseModel):
    """벤치마크 차트 데이터 응답 모델이다.

    Flutter _getList가 {"items": [...]} 형태에서 리스트를 추출한다.
    각 항목은 BenchmarkChartPoint.fromJson과 일치한다.
    """

    items: list[BenchmarkPeriodItem] = Field(default_factory=list)
    period: str = "1M"


# ---------------------------------------------------------------------------
# 의존성 주입
# ---------------------------------------------------------------------------

def set_benchmark_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("BenchmarkEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 내부 헬퍼: 캐시에서 일별 수익률 데이터를 조합한다
# ---------------------------------------------------------------------------

async def _build_period_items(
    cache: CacheClient,
    max_days: int,
) -> list[BenchmarkPeriodItem]:
    """AI 일별 수익률 + SPY/SSO 벤치마크 데이터를 합쳐 기간 항목 리스트를 생성한다.

    데이터 소스:
      - charts:daily_returns   : AI 포트폴리오 일별 PnL (chart_data_writer가 EOD에 기록)
      - benchmark:spy_daily    : SPY 일별 수익률 (벤치마크 모듈이 기록, 미연결 시 빈 값)
      - benchmark:sso_daily    : SSO 일별 수익률 (벤치마크 모듈이 기록, 미연결 시 빈 값)
    """
    # AI 포트폴리오 일별 수익률
    ai_raw: list[dict[str, Any]] = (
        await cache.read_json("charts:daily_returns") or []
    )
    # SPY/SSO 벤치마크 일별 수익률 (향후 벤치마크 모듈에서 기록)
    spy_raw: list[dict[str, Any]] = (
        await cache.read_json("benchmark:spy_daily") or []
    )
    sso_raw: list[dict[str, Any]] = (
        await cache.read_json("benchmark:sso_daily") or []
    )

    # 날짜 기준으로 인덱싱한다
    spy_by_date: dict[str, float] = {
        entry.get("date", ""): _safe_float(entry.get("return_pct"))
        for entry in spy_raw
    }
    sso_by_date: dict[str, float] = {
        entry.get("date", ""): _safe_float(entry.get("return_pct"))
        for entry in sso_raw
    }

    # 최근 max_days 일치로 슬라이싱한다
    sliced = ai_raw[-max_days:] if len(ai_raw) > max_days else ai_raw

    items: list[BenchmarkPeriodItem] = []
    for entry in sliced:
        date_str = entry.get("date", "")
        ai_pct = _safe_float(entry.get("pnl_pct"))
        spy_pct = spy_by_date.get(date_str, 0.0)
        sso_pct = sso_by_date.get(date_str, 0.0)
        items.append(BenchmarkPeriodItem(
            date=date_str,
            ai_return_pct=ai_pct,
            spy_return_pct=spy_pct,
            sso_return_pct=sso_pct,
            ai_vs_spy_diff=round(ai_pct - spy_pct, 4),
            ai_vs_sso_diff=round(ai_pct - sso_pct, 4),
        ))

    return items


def _compute_summary(items: list[BenchmarkPeriodItem]) -> BenchmarkSummaryItem:
    """기간 항목 리스트에서 요약 통계를 계산한다."""
    if not items:
        return BenchmarkSummaryItem()

    ai_total = round(sum(p.ai_return_pct for p in items), 4)
    spy_total = round(sum(p.spy_return_pct for p in items), 4)
    sso_total = round(sum(p.sso_return_pct for p in items), 4)

    total_days = len(items)
    # AI가 SPY/SSO를 이긴 날의 비율(승률)을 계산한다
    spy_wins = sum(1 for p in items if p.ai_return_pct > p.spy_return_pct)
    sso_wins = sum(1 for p in items if p.ai_return_pct > p.sso_return_pct)

    return BenchmarkSummaryItem(
        ai_total=ai_total,
        spy_total=spy_total,
        sso_total=sso_total,
        ai_win_rate_vs_spy=round(spy_wins / total_days, 4) if total_days else 0.0,
        ai_win_rate_vs_sso=round(sso_wins / total_days, 4) if total_days else 0.0,
    )


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전하게 float으로 변환한다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@benchmark_router.get("/comparison", response_model=BenchmarkComparisonResponse)
async def get_benchmark_comparison(
    period: str = "1M",
) -> BenchmarkComparisonResponse:
    """SPY/SSO 대비 AI 포트폴리오 수익률 비교를 반환한다.

    Flutter BenchmarkComparison 모델에 맞춰 periods + summary 구조로 응답한다.
    period 파라미터: 1W(7일), 1M(30일), 3M(90일), 6M(180일), 1Y(365일).
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        max_days = _PERIOD_DAYS.get(period, 30)
        items = await _build_period_items(cache, max_days)
        summary = _compute_summary(items)

        return BenchmarkComparisonResponse(
            periods=items,
            summary=summary,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("벤치마크 비교 조회 실패")
        raise HTTPException(status_code=500, detail="비교 조회 실패") from None


@benchmark_router.get("/chart", response_model=BenchmarkChartResponse)
async def get_benchmark_chart(
    period: str = "1M",
) -> BenchmarkChartResponse:
    """벤치마크 비교 차트 데이터를 반환한다.

    Flutter _getList가 {"items": [...]} 에서 리스트를 추출한다.
    각 항목은 BenchmarkChartPoint.fromJson과 일치:
      {"date", "ai_return_pct", "spy_return_pct", "sso_return_pct",
       "ai_vs_spy_diff", "ai_vs_sso_diff"}

    period 파라미터: 1W(7일), 1M(30일), 3M(90일), 6M(180일), 1Y(365일).
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        max_days = _PERIOD_DAYS.get(period, 30)
        items = await _build_period_items(cache, max_days)

        return BenchmarkChartResponse(items=items, period=period)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("벤치마크 차트 조회 실패: %s", period)
        raise HTTPException(status_code=500, detail="차트 조회 실패") from None
