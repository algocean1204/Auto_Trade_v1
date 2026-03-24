"""FxEndpoints -- USD/KRW 환율 조회 API이다.

현재 환율 현황 및 이력 데이터를 제공한다.
FxManager 인스턴스가 있으면 실시간 데이터를, 없으면 캐시 또는 기본값을 반환한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from src.monitoring.server.auth import verify_api_key
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

fx_router = APIRouter(prefix="/api/fx", tags=["fx"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None



def set_fx_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("FxEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 응답 모델 정의
# ---------------------------------------------------------------------------

class FxStatusResponse(BaseModel):
    """환율 현황 응답이다."""

    usd_krw_rate: float
    """현재 USD/KRW 환율이다."""
    change_pct: float
    """전일 대비 변동률(%)이다."""
    updated_at: str
    """마지막 업데이트 시각(ISO 8601)이다."""
    source: str
    """데이터 출처이다 (예: 'KIS', 'Naver-Mobile', 'Google-Finance', '조회불가')."""


class FxHistoryEntry(BaseModel):
    """환율 이력 항목이다."""

    date: str
    """날짜(YYYY-MM-DD)이다."""
    rate: float
    """해당일 환율이다."""
    change_pct: float
    """전일 대비 변동률(%)이다."""


class FxHistoryResponse(BaseModel):
    """환율 이력 응답이다."""

    entries: list[FxHistoryEntry] = Field(default_factory=list)
    """환율 이력 목록이다."""


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

@fx_router.get("/status", response_model=FxStatusResponse)
async def get_fx_status(_auth: str = Depends(verify_api_key)) -> FxStatusResponse:
    """현재 USD/KRW 환율 현황을 반환한다.

    FxScheduler가 10단계 폴백으로 갱신한 캐시를 우선 확인한다.
    캐시 미스 시 FxManager 실시간 조회를 시도한다.
    모든 소스 실패 시 rate=0.0, source='조회불가'를 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        # 1차: 캐시 확인 (FxScheduler가 10단계 폴백으로 갱신한 데이터)
        cache = _system.components.cache
        cached = await cache.read_json("fx:current")
        if cached and isinstance(cached, dict):
            rate_val = float(cached.get("usd_krw_rate", 0))
            if 900 < rate_val < 2000:
                return FxStatusResponse(
                    usd_krw_rate=rate_val,
                    change_pct=float(cached.get("change_pct", 0.0)),
                    updated_at=str(cached.get("updated_at", "")),
                    source=str(cached.get("source", "cache")),
                )

        # 2차: FxManager 실시간 조회 (캐시 비정상인 경우)
        fx_manager = _system.features.get("fx_manager")
        if fx_manager is not None:
            fx_rate = await fx_manager.get_rate()
            if fx_rate is not None:
                rate_val = float(fx_rate.usd_krw)
                if 900 < rate_val < 2000:
                    return FxStatusResponse(
                        usd_krw_rate=rate_val,
                        change_pct=0.0,
                        updated_at=fx_rate.last_updated.isoformat(),
                        source="KIS",
                    )

        # 모든 소스 실패: 조회불가
        return FxStatusResponse(
            usd_krw_rate=0.0,
            change_pct=0.0,
            updated_at="",
            source="조회불가",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("환율 현황 조회 실패")
        raise HTTPException(status_code=500, detail="환율 현황 조회 중 오류가 발생했다") from None


@fx_router.get("/history", response_model=FxHistoryResponse)
async def get_fx_history(limit: int = Query(default=30, ge=1, le=365), _auth: str = Depends(verify_api_key)) -> FxHistoryResponse:
    """USD/KRW 환율 이력을 반환한다.

    캐시 키 fx:history에서 데이터를 읽는다.
    캐시 미스 시 빈 목록을 반환한다.

    Args:
        limit: 반환할 최대 항목 수이다 (기본 30일).
    """
    if _system is None:
        return FxHistoryResponse(entries=[])
    try:
        cache = _system.components.cache
        cached = await cache.read_json("fx:history")
        if cached and isinstance(cached, list):
            # 최신 항목이 리스트 끝에 위치하므로 뒤에서부터 limit개를 역순으로 가져온다
            recent = cached[-limit:] if len(cached) > limit else cached
            entries = [
                FxHistoryEntry(
                    date=str(e.get("date", "")),
                    rate=float(e.get("rate", 0.0)),
                    change_pct=float(e.get("change_pct", 0.0)),
                )
                for e in reversed(recent)
            ]
            return FxHistoryResponse(entries=entries)
        return FxHistoryResponse(entries=[])
    except Exception:
        _logger.exception("환율 이력 조회 실패")
        raise HTTPException(status_code=500, detail="환율 이력 조회 중 오류가 발생했다") from None
