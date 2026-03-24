"""F7.25 ChartsEndpoints -- 차트 데이터 API이다.

일별 수익률, 누적 수익률, 히트맵, 낙폭 차트 데이터를 제공한다.
캐시에서 읽으며, 캐시 미스 시 DB(DailyPnlLog)에서 폴백한다.
Flutter 대시보드에서 /dashboard/charts/* 경로로 호출한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from src.monitoring.server.auth import verify_api_key
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.db.models import DailyPnlLog

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


async def _build_daily_returns_from_db(days: int) -> list[dict[str, Any]]:
    """DB daily_pnl_log에서 일별 수익률 차트 데이터를 생성한다.

    캐시 미스 시 폴백으로 호출된다. 결과를 캐시에 저장하여 반복 쿼리를 방지한다.
    """
    if _system is None:
        return []
    try:
        db = _system.components.db
        async with db.get_session() as session:
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.asc())
                .limit(365)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                return []
            # ORM 속성은 세션 컨텍스트 내에서 접근해야 DetachedInstanceError를 방지한다
            data = [
                {
                    "date": str(r.date) if r.date else "",
                    "pnl": r.pnl_amount or 0.0,
                    "pnl_pct": r.pnl_pct or 0.0,
                }
                for r in rows
            ]
        # 캐시에 저장하여 반복 DB 쿼리를 방지한다 (EOD 갱신과 동일한 90일 TTL)
        try:
            cache = _system.components.cache
            await cache.write_json("charts:daily_returns", data, ttl=86400 * 90)
        except Exception:
            _logger.debug("일별 수익률 차트 캐시 저장 실패 (무시)")
        return data[-days:] if len(data) > days else data
    except Exception:
        _logger.warning("DB에서 일별 수익률 차트 조회 실패")
        return []


async def _build_drawdown_from_db(days: int) -> list[dict[str, Any]]:
    """DB daily_pnl_log에서 낙폭(drawdown) 차트 데이터를 생성한다.

    equity 컬럼의 고점 대비 하락률을 계산한다.
    """
    if _system is None:
        return []
    try:
        db = _system.components.db
        async with db.get_session() as session:
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.asc())
                .limit(365)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                return []
            # ORM 속성은 세션 컨텍스트 내에서 접근해야 DetachedInstanceError를 방지한다
            peak = 0.0
            data: list[dict[str, Any]] = []
            for r in rows:
                equity = r.equity or 0.0
                if equity > peak:
                    peak = equity
                dd_pct = ((equity - peak) / peak * 100.0) if peak > 0 else 0.0
                data.append({
                    "date": str(r.date) if r.date else "",
                    "drawdown_pct": round(dd_pct, 4),
                })
        # 캐시에 저장하여 반복 DB 쿼리를 방지한다 (EOD 갱신과 동일한 90일 TTL)
        try:
            cache = _system.components.cache
            await cache.write_json("charts:drawdown", data, ttl=86400 * 90)
        except Exception:
            _logger.debug("낙폭 차트 캐시 저장 실패 (무시)")
        return data[-days:] if len(data) > days else data
    except Exception:
        _logger.warning("DB에서 낙폭 차트 조회 실패")
        return []


async def _build_cumulative_from_db(days: int) -> list[dict[str, Any]]:
    """DB daily_pnl_log에서 누적 수익률 차트 데이터를 생성한다.

    일별 pnl_pct를 누적 합산하여 cumulative_pct를 계산한다.
    benchmark_pct는 DB에 없으므로 0.0으로 채운다.
    """
    if _system is None:
        return []
    try:
        db = _system.components.db
        async with db.get_session() as session:
            stmt = (
                select(DailyPnlLog)
                .order_by(DailyPnlLog.date.asc())
                .limit(365)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                return []
            # ORM 속성은 세션 컨텍스트 내에서 접근해야 DetachedInstanceError를 방지한다
            cumulative = 0.0
            data: list[dict[str, Any]] = []
            for r in rows:
                cumulative += r.pnl_pct or 0.0
                data.append({
                    "date": str(r.date) if r.date else "",
                    "cumulative_pct": round(cumulative, 4),
                    "benchmark_pct": 0.0,
                })
        # 캐시에 저장하여 반복 DB 쿼리를 방지한다 (EOD 갱신과 동일한 90일 TTL)
        try:
            cache = _system.components.cache
            await cache.write_json("charts:cumulative_returns", data, ttl=86400 * 90)
        except Exception:
            _logger.debug("누적 수익률 차트 캐시 저장 실패 (무시)")
        return data[-days:] if len(data) > days else data
    except Exception:
        _logger.warning("DB에서 누적 수익률 차트 조회 실패")
        return []


@charts_router.get("/daily-returns", response_model=ChartListResponse)
async def get_daily_returns(days: int = Query(default=30, ge=1, le=365), _auth: str = Depends(verify_api_key)) -> ChartListResponse:
    """일별 PnL 수익률 목록을 반환한다.

    캐시 키: charts:daily_returns
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
        if raw:
            # days 파라미터로 최근 N일 슬라이싱
            sliced = raw[-days:] if len(raw) > days else raw
            return ChartListResponse(data=sliced, count=len(sliced))
        # 캐시 미스 시 DB fallback
        db_data = await _build_daily_returns_from_db(days)
        return ChartListResponse(data=db_data, count=len(db_data))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 수익률 조회 실패")
        raise HTTPException(status_code=500, detail="일별 수익률 조회 실패") from None


@charts_router.get("/cumulative", response_model=ChartListResponse)
async def get_cumulative_returns(
    days: int = Query(default=90, ge=1, le=365),
    _auth: str = Depends(verify_api_key),
) -> ChartListResponse:
    """누적 수익률 데이터를 반환한다.

    캐시 키: charts:cumulative_returns
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
        if raw:
            # 최근 N일로 제한하여 대량 데이터 응답을 방지한다
            sliced = raw[-days:] if len(raw) > days else raw
            return ChartListResponse(data=sliced, count=len(sliced))
        # 캐시 미스 시 DB fallback: DailyPnlLog에서 누적 합산한다
        db_data = await _build_cumulative_from_db(days)
        return ChartListResponse(data=db_data, count=len(db_data))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("누적 수익률 조회 실패")
        raise HTTPException(status_code=500, detail="누적 수익률 조회 실패") from None


@charts_router.get("/heatmap/ticker", response_model=ChartListResponse)
async def get_ticker_heatmap(days: int = Query(default=30, ge=1, le=365), _auth: str = Depends(verify_api_key)) -> ChartListResponse:
    """티커별 히트맵 데이터를 반환한다.

    캐시 키: charts:heatmap_ticker
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
async def get_hourly_heatmap(_auth: str = Depends(verify_api_key)) -> ChartListResponse:
    """시간대별 히트맵 데이터를 반환한다.

    캐시 키: charts:heatmap_hourly
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
async def get_drawdown(
    days: int = Query(default=90, ge=1, le=365),
    _auth: str = Depends(verify_api_key),
) -> ChartListResponse:
    """최대 낙폭(Drawdown) 데이터를 반환한다.

    캐시 키: charts:drawdown
    Flutter DrawdownPoint.fromJson 형식:
      [{"date": "YYYY-MM-DD", "drawdown_pct": float}, ...]
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # read_json을 사용해야 JSON 문자열을 list로 파싱할 수 있다
        raw: list = await cache.read_json("charts:drawdown") or []
        if raw:
            # 최근 N일로 제한하여 대량 데이터 응답을 방지한다
            sliced = raw[-days:] if len(raw) > days else raw
            return ChartListResponse(data=sliced, count=len(sliced))
        # 캐시 미스 시 DB fallback: DailyPnlLog equity에서 drawdown 계산한다
        db_data = await _build_drawdown_from_db(days)
        return ChartListResponse(data=db_data, count=len(db_data))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("낙폭 데이터 조회 실패")
        raise HTTPException(status_code=500, detail="낙폭 조회 실패") from None
