"""TaxEndpoints -- 세금 관련 조회 API이다.

YTD 세금 현황, 연간 리포트, 세금 손실 수확 제안을 제공한다.
데이터는 캐시에서 읽고, 없으면 기본값(0)을 반환한다.

Flutter 대시보드 Dart 모델(tax_models.dart)과 구조를 일치시킨다.
"""
from __future__ import annotations

from datetime import datetime
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

# 한국 양도소득세 기본 공제액(KRW)이다.
_ANNUAL_EXEMPTION_KRW = 2_500_000
# 기본 세율 22% (양도소득세 20% + 지방소득세 2%)이다.
_DEFAULT_TAX_RATE = 0.22
# 기본 환율(KRW/USD)이다. 캐시에 환율 정보가 없을 때 사용한다.
_DEFAULT_FX_RATE = 1350.0


def set_tax_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("TaxEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 응답 모델 정의 — Flutter tax_models.dart 구조와 일치시킨다
# ---------------------------------------------------------------------------

class TaxSummaryModel(BaseModel):
    """세금 요약 정보이다. Dart TaxSummary.fromJson()과 매핑된다."""

    total_gain_usd: float
    """연초부터 현재까지 총 이익(USD)이다."""
    total_loss_usd: float
    """연초부터 현재까지 총 손실(USD)이다."""
    net_gain_usd: float
    """순 손익(USD)이다."""
    net_gain_krw: float
    """순 손익(KRW)이다."""
    exemption_krw: float
    """연간 기본 공제액(KRW)이다. 2,500,000원."""
    taxable_krw: float
    """과세 대상 금액(KRW)이다. max(net_gain_krw - exemption_krw, 0)."""
    estimated_tax_krw: float
    """추정 세금(KRW)이다. taxable_krw * tax_rate."""
    tax_rate: float
    """적용 세율이다. 기본 0.22 (22%)."""


class RemainingExemptionModel(BaseModel):
    """기본 공제 잔여 정보이다. Dart RemainingExemption.fromJson()과 매핑된다."""

    exemption_krw: float
    """연간 기본 공제 총액(KRW)이다."""
    used_krw: float
    """이미 사용한 공제액(KRW)이다."""
    remaining_krw: float
    """남은 공제액(KRW)이다."""
    utilization_pct: float
    """공제 사용률(0.0 ~ 100.0)이다."""


class TaxStatusResponse(BaseModel):
    """세금 현황 응답이다. Dart TaxStatus.fromJson()과 매핑된다."""

    year: int
    """과세 연도이다."""
    summary: TaxSummaryModel
    """세금 요약 정보이다."""
    remaining_exemption: RemainingExemptionModel
    """기본 공제 잔여 정보이다."""


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
    """세금 손실 수확 제안 항목이다. Dart TaxHarvestSuggestion.fromJson()과 매핑된다."""

    ticker: str
    unrealized_loss_usd: float
    """미실현 손실(USD)이다."""
    potential_tax_saving_krw: float
    """예상 세금 절감액(KRW)이다."""
    recommendation: str
    """추천 행동이다. 예: '매도 추천', '워시세일 위험'."""


class TaxHarvestResponse(BaseModel):
    """세금 손실 수확 제안 응답이다."""

    suggestions: list[HarvestSuggestion]
    """손실 수확 제안 목록이다."""


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

def _build_default_tax_status() -> TaxStatusResponse:
    """캐시 미스/시스템 미초기화 시 기본 세금 현황을 생성한다."""
    return TaxStatusResponse(
        year=datetime.now().year,
        summary=TaxSummaryModel(
            total_gain_usd=0.0,
            total_loss_usd=0.0,
            net_gain_usd=0.0,
            net_gain_krw=0.0,
            exemption_krw=_ANNUAL_EXEMPTION_KRW,
            taxable_krw=0.0,
            estimated_tax_krw=0.0,
            tax_rate=_DEFAULT_TAX_RATE,
        ),
        remaining_exemption=RemainingExemptionModel(
            exemption_krw=_ANNUAL_EXEMPTION_KRW,
            used_krw=0.0,
            remaining_krw=_ANNUAL_EXEMPTION_KRW,
            utilization_pct=0.0,
        ),
    )


def _build_tax_status_from_cache(cached: dict) -> TaxStatusResponse:
    """캐시 데이터로부터 세금 현황 응답을 구성한다.

    캐시에 새 구조(summary/remaining_exemption)가 있으면 그대로 사용하고,
    레거시 구조(ytd_realized_pnl 등 플랫 필드)만 있으면 변환한다.
    """
    # 새 구조가 이미 캐시에 저장된 경우 직접 매핑한다
    if "summary" in cached:
        raw_summary = cached.get("summary", {})
        raw_remaining = cached.get("remaining_exemption", {})
        return TaxStatusResponse(
            year=int(cached.get("year", datetime.now().year)),
            summary=TaxSummaryModel(
                total_gain_usd=float(raw_summary.get("total_gain_usd", 0.0)),
                total_loss_usd=float(raw_summary.get("total_loss_usd", 0.0)),
                net_gain_usd=float(raw_summary.get("net_gain_usd", 0.0)),
                net_gain_krw=float(raw_summary.get("net_gain_krw", 0.0)),
                exemption_krw=float(raw_summary.get("exemption_krw", _ANNUAL_EXEMPTION_KRW)),
                taxable_krw=float(raw_summary.get("taxable_krw", 0.0)),
                estimated_tax_krw=float(raw_summary.get("estimated_tax_krw", 0.0)),
                tax_rate=float(raw_summary.get("tax_rate", _DEFAULT_TAX_RATE)),
            ),
            remaining_exemption=RemainingExemptionModel(
                exemption_krw=float(raw_remaining.get("exemption_krw", _ANNUAL_EXEMPTION_KRW)),
                used_krw=float(raw_remaining.get("used_krw", 0.0)),
                remaining_krw=float(raw_remaining.get("remaining_krw", _ANNUAL_EXEMPTION_KRW)),
                utilization_pct=float(raw_remaining.get("utilization_pct", 0.0)),
            ),
        )

    # 레거시 플랫 구조 → 새 구조로 변환한다
    ytd_pnl = float(cached.get("ytd_realized_pnl", 0.0))
    fx_rate = float(cached.get("fx_rate", _DEFAULT_FX_RATE))

    # 이익/손실 분리: ytd_pnl이 양수면 이익, 음수면 손실로 분류한다
    total_gain = max(ytd_pnl, 0.0)
    total_loss = abs(min(ytd_pnl, 0.0))
    net_gain_krw = ytd_pnl * fx_rate

    # 과세 대상 금액 계산한다
    taxable_krw = max(net_gain_krw - _ANNUAL_EXEMPTION_KRW, 0.0)
    estimated_tax_krw = taxable_krw * _DEFAULT_TAX_RATE

    # 공제 사용 현황 계산한다
    used_krw = min(max(net_gain_krw, 0.0), _ANNUAL_EXEMPTION_KRW)
    remaining_krw = _ANNUAL_EXEMPTION_KRW - used_krw
    utilization_pct = (used_krw / _ANNUAL_EXEMPTION_KRW * 100.0) if _ANNUAL_EXEMPTION_KRW > 0 else 0.0

    return TaxStatusResponse(
        year=int(cached.get("year", datetime.now().year)),
        summary=TaxSummaryModel(
            total_gain_usd=total_gain,
            total_loss_usd=total_loss,
            net_gain_usd=ytd_pnl,
            net_gain_krw=net_gain_krw,
            exemption_krw=_ANNUAL_EXEMPTION_KRW,
            taxable_krw=taxable_krw,
            estimated_tax_krw=estimated_tax_krw,
            tax_rate=_DEFAULT_TAX_RATE,
        ),
        remaining_exemption=RemainingExemptionModel(
            exemption_krw=_ANNUAL_EXEMPTION_KRW,
            used_krw=used_krw,
            remaining_krw=remaining_krw,
            utilization_pct=utilization_pct,
        ),
    )


@tax_router.get("/status", response_model=TaxStatusResponse)
async def get_tax_status() -> TaxStatusResponse:
    """연초 대비 현재 세금 현황을 반환한다.

    1차: tax:status 캐시에서 읽는다.
    2차: 캐시 미스 시 trades:today에서 실현 PnL을 합산하여 계산한다.
    Dart TaxStatus.fromJson()이 기대하는 중첩 구조를 반환한다.
    """
    if _system is None:
        _logger.debug("시스템 미초기화 -- 기본 세금 현황 반환")
        return _build_default_tax_status()
    try:
        cache = _system.components.cache

        # 1차: tax:status 전용 캐시 키
        cached = await cache.read_json("tax:status")
        if cached and isinstance(cached, dict):
            return _build_tax_status_from_cache(cached)

        # 2차: trades:today에서 실현 PnL 합산 (폴백)
        today_trades = await cache.read_json("trades:today")
        if today_trades and isinstance(today_trades, list):
            total_gain = 0.0
            total_loss = 0.0
            for t in today_trades:
                if isinstance(t, dict) and t.get("side") == "sell":
                    pnl = t.get("pnl")
                    if pnl is not None and isinstance(pnl, (int, float)):
                        if pnl >= 0:
                            total_gain += pnl
                        else:
                            total_loss += abs(pnl)

            if total_gain > 0 or total_loss > 0:
                net_gain_usd = total_gain - total_loss
                net_gain_krw = net_gain_usd * _DEFAULT_FX_RATE
                taxable_krw = max(net_gain_krw - _ANNUAL_EXEMPTION_KRW, 0.0)
                estimated_tax = taxable_krw * _DEFAULT_TAX_RATE
                used_krw = min(max(net_gain_krw, 0.0), _ANNUAL_EXEMPTION_KRW)
                remaining_krw = _ANNUAL_EXEMPTION_KRW - used_krw
                utilization_pct = (used_krw / _ANNUAL_EXEMPTION_KRW * 100) if _ANNUAL_EXEMPTION_KRW > 0 else 0.0

                return TaxStatusResponse(
                    year=datetime.now().year,
                    summary=TaxSummaryModel(
                        total_gain_usd=total_gain,
                        total_loss_usd=total_loss,
                        net_gain_usd=net_gain_usd,
                        net_gain_krw=net_gain_krw,
                        exemption_krw=_ANNUAL_EXEMPTION_KRW,
                        taxable_krw=taxable_krw,
                        estimated_tax_krw=estimated_tax,
                        tax_rate=_DEFAULT_TAX_RATE,
                    ),
                    remaining_exemption=RemainingExemptionModel(
                        exemption_krw=_ANNUAL_EXEMPTION_KRW,
                        used_krw=used_krw,
                        remaining_krw=remaining_krw,
                        utilization_pct=utilization_pct,
                    ),
                )

        return _build_default_tax_status()
    except Exception:
        _logger.exception("세금 현황 조회 실패")
        raise HTTPException(status_code=500, detail="세금 현황 조회 중 오류가 발생했다") from None


@tax_router.get("/report", response_model=TaxReportResponse)
async def get_tax_report(year: int = 2026) -> TaxReportResponse:
    """연간 세금 리포트를 반환한다.

    캐시 키 tax:report:{year}에서 데이터를 읽는다.
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


def _convert_harvest_suggestion(raw: dict) -> HarvestSuggestion:
    """캐시의 수확 제안 항목을 Dart 모델 구조에 맞게 변환한다.

    레거시 필드(unrealized_loss, potential_savings, wash_sale_risk)와
    새 필드(unrealized_loss_usd, potential_tax_saving_krw, recommendation) 모두 처리한다.
    """
    ticker = str(raw.get("ticker", ""))

    # unrealized_loss_usd: 새 필드 우선, 레거시 폴백한다
    unrealized_loss_usd = float(
        raw.get("unrealized_loss_usd", raw.get("unrealized_loss", 0.0)),
    )

    # potential_tax_saving_krw: 새 필드 우선, 레거시 폴백한다
    potential_tax_saving_krw = float(
        raw.get("potential_tax_saving_krw", raw.get("potential_savings", 0.0)),
    )

    # recommendation: 새 필드가 있으면 사용, 없으면 wash_sale_risk bool에서 변환한다
    if "recommendation" in raw:
        recommendation = str(raw["recommendation"])
    else:
        wash_sale_risk = bool(raw.get("wash_sale_risk", False))
        recommendation = "워시세일 위험" if wash_sale_risk else "매도 추천"

    return HarvestSuggestion(
        ticker=ticker,
        unrealized_loss_usd=unrealized_loss_usd,
        potential_tax_saving_krw=potential_tax_saving_krw,
        recommendation=recommendation,
    )


@tax_router.get("/harvest-suggestions", response_model=TaxHarvestResponse)
async def get_harvest_suggestions() -> TaxHarvestResponse:
    """세금 손실 수확 제안 목록을 반환한다.

    캐시 키 tax:harvest에서 데이터를 읽는다.
    캐시 미스 시 빈 목록을 반환한다.
    Dart TaxHarvestSuggestion.fromJson()이 기대하는 필드명으로 반환한다.
    """
    if _system is None:
        return TaxHarvestResponse(suggestions=[])
    try:
        cache = _system.components.cache
        cached = await cache.read_json("tax:harvest")
        if cached and isinstance(cached, list):
            suggestions = [
                _convert_harvest_suggestion(s) for s in cached if isinstance(s, dict)
            ]
            return TaxHarvestResponse(suggestions=suggestions)
        return TaxHarvestResponse(suggestions=[])
    except Exception:
        _logger.exception("손실 수확 제안 조회 실패")
        raise HTTPException(status_code=500, detail="손실 수확 제안 조회 중 오류가 발생했다") from None
