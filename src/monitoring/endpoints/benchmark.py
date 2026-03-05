"""F7.10 BenchmarkEndpoints -- 벤치마크 비교 API이다.

SPY/QQQ 대비 포트폴리오 수익률 비교 및 차트 데이터를 제공한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

benchmark_router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_system: InjectedSystem | None = None


class BenchmarkComparisonResponse(BaseModel):
    """벤치마크 비교 응답 모델이다."""

    portfolio_return: float = 0.0
    spy_return: float = 0.0
    qqq_return: float = 0.0
    alpha_vs_spy: float = 0.0
    alpha_vs_qqq: float = 0.0
    period: str = "daily"
    message: str = ""


class BenchmarkChartResponse(BaseModel):
    """벤치마크 차트 응답 모델이다."""

    period: str
    portfolio_series: list[dict[str, Any]] = Field(default_factory=list)
    spy_series: list[dict[str, Any]] = Field(default_factory=list)
    qqq_series: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""


def set_benchmark_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("BenchmarkEndpoints 의존성 주입 완료")


@benchmark_router.get("/comparison", response_model=BenchmarkComparisonResponse)
async def get_benchmark_comparison() -> BenchmarkComparisonResponse:
    """SPY/QQQ 대비 포트폴리오 수익률을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("benchmark:comparison")
        if cached and isinstance(cached, dict):
            return BenchmarkComparisonResponse(
                portfolio_return=cached.get("portfolio_return", 0.0),
                spy_return=cached.get("spy_return", 0.0),
                qqq_return=cached.get("qqq_return", 0.0),
                alpha_vs_spy=cached.get("alpha_vs_spy", 0.0),
                alpha_vs_qqq=cached.get("alpha_vs_qqq", 0.0),
                period=cached.get("period", "daily"),
                message=cached.get("message", ""),
            )
        return BenchmarkComparisonResponse(
            message="벤치마크 데이터가 없다",
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
    """벤치마크 비교 차트 데이터를 반환한다. period: 1W, 1M, 3M, 6M, 1Y."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        key = f"benchmark:chart:{period}"
        cached = await cache.read_json(key)
        if cached and isinstance(cached, dict):
            return BenchmarkChartResponse(
                period=cached.get("period", period),
                portfolio_series=cached.get("portfolio_series", []),
                spy_series=cached.get("spy_series", []),
                qqq_series=cached.get("qqq_series", []),
                message=cached.get("message", ""),
            )
        return BenchmarkChartResponse(
            period=period,
            message="차트 데이터가 없다",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("벤치마크 차트 조회 실패: %s", period)
        raise HTTPException(status_code=500, detail="차트 조회 실패") from None
