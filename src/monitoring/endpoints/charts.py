"""F7.25 ChartsEndpoints -- 차트 데이터 API이다.

일별 수익률, 누적 수익률, 히트맵, 낙폭 차트 데이터를 제공한다.
Redis 캐시에서 읽으며, 데이터 없으면 빈 배열을 반환한다.
Flutter 대시보드에서 /dashboard/charts/* 경로로 호출한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# /api/dashboard 접두어 아래 /charts/* 경로를 추가한다
# dashboard_router 가 /api/dashboard 이므로 여기는 같은 prefix를 공유한다
charts_router = APIRouter(prefix="/api/dashboard/charts", tags=["charts"])

_system: InjectedSystem | None = None


class ChartListResponse(BaseModel):
    """차트 데이터 목록 응답 모델이다."""

    data: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


def set_charts_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("ChartsEndpoints 의존성 주입 완료")


@charts_router.get("/daily-returns", response_model=ChartListResponse)
async def get_daily_returns(days: int = 30) -> ChartListResponse:
    """일별 PnL 수익률 목록을 반환한다.

    Redis 캐시 키: charts:daily_returns
    EOD 시퀀스에서 저장한다. 데이터 없으면 빈 배열 반환.
    Flutter DailyReturn.fromJson 형식:
      [{"date": "YYYY-MM-DD", "pnl": float, "pnl_pct": float}, ...]
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # read_json을 사용해야 JSON 문자열을 list로 파싱할 수 있다
        raw: list = await cache.read_json("charts:daily_returns") or []
        # days 파라미터로 최근 N일 슬라이싱
        sliced = raw[-days:] if len(raw) > days else raw
        return ChartListResponse(data=sliced, count=len(sliced))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 수익률 조회 실패")
        raise HTTPException(status_code=500, detail="일별 수익률 조회 실패") from None


@charts_router.get("/cumulative", response_model=ChartListResponse)
async def get_cumulative_returns() -> ChartListResponse:
    """누적 수익률 데이터를 반환한다.

    Redis 캐시 키: charts:cumulative_returns
    데이터가 없는 경우 빈 배열을 반환한다.
    Flutter CumulativeReturn.fromJson 형식:
      [{"date": "YYYY-MM-DD", "cumulative_pct": float, "benchmark_pct": float}, ...]
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # read_json을 사용해야 JSON 문자열을 list로 파싱할 수 있다
        raw: list = await cache.read_json("charts:cumulative_returns") or []
        return ChartListResponse(data=raw, count=len(raw))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("누적 수익률 조회 실패")
        raise HTTPException(status_code=500, detail="누적 수익률 조회 실패") from None


@charts_router.get("/heatmap/ticker", response_model=ChartListResponse)
async def get_ticker_heatmap(days: int = 30) -> ChartListResponse:
    """티커별 히트맵 데이터를 반환한다.

    Redis 캐시 키: charts:heatmap_ticker
    Flutter HeatmapPoint.fromJson 형식:
      [{"ticker": str, "value": float, "label": str}, ...]
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # read_json을 사용해야 JSON 문자열을 list로 파싱할 수 있다
        raw: list = await cache.read_json("charts:heatmap_ticker") or []
        return ChartListResponse(data=raw, count=len(raw))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 히트맵 조회 실패")
        raise HTTPException(status_code=500, detail="히트맵 조회 실패") from None


@charts_router.get("/heatmap/hourly", response_model=ChartListResponse)
async def get_hourly_heatmap() -> ChartListResponse:
    """시간대별 히트맵 데이터를 반환한다.

    Redis 캐시 키: charts:heatmap_hourly
    Flutter HeatmapPoint.fromJson 형식:
      [{"hour": int, "value": float, "label": str}, ...]
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # read_json을 사용해야 JSON 문자열을 list로 파싱할 수 있다
        raw: list = await cache.read_json("charts:heatmap_hourly") or []
        return ChartListResponse(data=raw, count=len(raw))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("시간대 히트맵 조회 실패")
        raise HTTPException(status_code=500, detail="히트맵 조회 실패") from None


@charts_router.get("/drawdown", response_model=ChartListResponse)
async def get_drawdown() -> ChartListResponse:
    """최대 낙폭(Drawdown) 데이터를 반환한다.

    Redis 캐시 키: charts:drawdown
    Flutter DrawdownPoint.fromJson 형식:
      [{"date": "YYYY-MM-DD", "drawdown_pct": float}, ...]
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # read_json을 사용해야 JSON 문자열을 list로 파싱할 수 있다
        raw: list = await cache.read_json("charts:drawdown") or []
        return ChartListResponse(data=raw, count=len(raw))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("낙폭 데이터 조회 실패")
        raise HTTPException(status_code=500, detail="낙폭 조회 실패") from None
