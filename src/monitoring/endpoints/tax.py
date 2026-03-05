"""TaxEndpoints -- 세금 관련 조회 API이다.

YTD 세금 현황, 연간 리포트, 세금 손실 수확 제안을 제공한다.
데이터는 Redis 캐시에서 읽고, 없으면 기본값(0)을 반환한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

tax_router = APIRouter(prefix="/api/tax", tags=["tax"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None


def set_tax_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("TaxEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 응답 모델 정의
# ---------------------------------------------------------------------------

class TaxStatusResponse(BaseModel):
    """세금 현황 응답이다."""

    ytd_realized_pnl: float
    """연초부터 현재까지 실현 손익(USD)이다."""
    estimated_tax: float
    """추정 세금(KRW)이다. 22% 양도소득세 기준이다."""
    wash_sale_count: int
    """Wash Sale 횟수이다."""
    tax_bracket: str
    """세금 구간 레이블이다 (예: '22%')."""


class TaxTransaction(BaseModel):
    """개별 세금 거래 기록이다."""

    ticker: str
    gain_usd: float
    tax_krw: float
    fx_rate: float
    date: str


class TaxReportResponse(BaseModel):
    """연간 세금 리포트 응답이다."""

    year: int
    total_gains: float
    """총 이익(USD)이다."""
    total_losses: float
    """총 손실(USD)이다."""
    net_gain: float
    """순 손익(USD)이다."""
    short_term: float
    """단기 손익(1년 미만, USD)이다."""
    long_term: float
    """장기 손익(1년 이상, USD)이다."""
    wash_sales: int
    """Wash Sale 건수이다."""
    transactions: list[TaxTransaction]
    """개별 거래 목록이다."""


class HarvestSuggestion(BaseModel):
    """세금 손실 수확 제안 항목이다."""

    ticker: str
    unrealized_loss: float
    """미실현 손실(USD)이다."""
    potential_savings: float
    """예상 세금 절감액(KRW)이다."""
    wash_sale_risk: bool
    """Wash Sale 위험 여부이다."""


class TaxHarvestResponse(BaseModel):
    """세금 손실 수확 제안 응답이다."""

    suggestions: list[HarvestSuggestion]
    """손실 수확 제안 목록이다."""


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

@tax_router.get("/status", response_model=TaxStatusResponse)
async def get_tax_status() -> TaxStatusResponse:
    """연초 대비 현재 세금 현황을 반환한다.

    Redis 캐시 키 tax:status에서 데이터를 읽는다.
    캐시 미스 시 기본값(0)으로 응답한다.
    """
    if _system is None:
        _logger.debug("시스템 미초기화 -- 기본 세금 현황 반환")
        return TaxStatusResponse(
            ytd_realized_pnl=0.0,
            estimated_tax=0.0,
            wash_sale_count=0,
            tax_bracket="22%",
        )
    try:
        cache = _system.components.cache
        cached = await cache.read_json("tax:status")
        if cached and isinstance(cached, dict):
            return TaxStatusResponse(
                ytd_realized_pnl=float(cached.get("ytd_realized_pnl", 0.0)),
                estimated_tax=float(cached.get("estimated_tax", 0.0)),
                wash_sale_count=int(cached.get("wash_sale_count", 0)),
                tax_bracket=str(cached.get("tax_bracket", "22%")),
            )
        return TaxStatusResponse(
            ytd_realized_pnl=0.0,
            estimated_tax=0.0,
            wash_sale_count=0,
            tax_bracket="22%",
        )
    except Exception:
        _logger.exception("세금 현황 조회 실패")
        raise HTTPException(status_code=500, detail="세금 현황 조회 중 오류가 발생했다") from None


@tax_router.get("/report", response_model=TaxReportResponse)
async def get_tax_report(year: int = 2026) -> TaxReportResponse:
    """연간 세금 리포트를 반환한다.

    Redis 캐시 키 tax:report:{year}에서 데이터를 읽는다.
    캐시 미스 시 기본값(0, 빈 목록)으로 응답한다.
    """
    if _system is None:
        return TaxReportResponse(
            year=year,
            total_gains=0.0,
            total_losses=0.0,
            net_gain=0.0,
            short_term=0.0,
            long_term=0.0,
            wash_sales=0,
            transactions=[],
        )
    try:
        cache = _system.components.cache
        cached = await cache.read_json(f"tax:report:{year}")
        if cached and isinstance(cached, dict):
            raw_txns = cached.get("transactions", [])
            transactions = [
                TaxTransaction(
                    ticker=str(t.get("ticker", "")),
                    gain_usd=float(t.get("gain_usd", 0.0)),
                    tax_krw=float(t.get("tax_krw", 0.0)),
                    fx_rate=float(t.get("fx_rate", 1350.0)),
                    date=str(t.get("date", "")),
                )
                for t in (raw_txns if isinstance(raw_txns, list) else [])
            ]
            return TaxReportResponse(
                year=year,
                total_gains=float(cached.get("total_gains", 0.0)),
                total_losses=float(cached.get("total_losses", 0.0)),
                net_gain=float(cached.get("net_gain", 0.0)),
                short_term=float(cached.get("short_term", 0.0)),
                long_term=float(cached.get("long_term", 0.0)),
                wash_sales=int(cached.get("wash_sales", 0)),
                transactions=transactions,
            )
        return TaxReportResponse(
            year=year,
            total_gains=0.0,
            total_losses=0.0,
            net_gain=0.0,
            short_term=0.0,
            long_term=0.0,
            wash_sales=0,
            transactions=[],
        )
    except Exception:
        _logger.exception("세금 리포트 조회 실패 (year=%d)", year)
        raise HTTPException(status_code=500, detail="세금 리포트 조회 중 오류가 발생했다") from None


@tax_router.get("/harvest-suggestions", response_model=TaxHarvestResponse)
async def get_harvest_suggestions() -> TaxHarvestResponse:
    """세금 손실 수확 제안 목록을 반환한다.

    Redis 캐시 키 tax:harvest에서 데이터를 읽는다.
    캐시 미스 시 빈 목록을 반환한다.
    """
    if _system is None:
        return TaxHarvestResponse(suggestions=[])
    try:
        cache = _system.components.cache
        cached = await cache.read_json("tax:harvest")
        if cached and isinstance(cached, list):
            suggestions = [
                HarvestSuggestion(
                    ticker=str(s.get("ticker", "")),
                    unrealized_loss=float(s.get("unrealized_loss", 0.0)),
                    potential_savings=float(s.get("potential_savings", 0.0)),
                    wash_sale_risk=bool(s.get("wash_sale_risk", False)),
                )
                for s in cached
            ]
            return TaxHarvestResponse(suggestions=suggestions)
        return TaxHarvestResponse(suggestions=[])
    except Exception:
        _logger.exception("손실 수확 제안 조회 실패")
        raise HTTPException(status_code=500, detail="손실 수확 제안 조회 중 오류가 발생했다") from None
