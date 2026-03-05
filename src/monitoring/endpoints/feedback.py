"""F7.24 FeedbackEndpoints -- 피드백/리포트 조회 API이다.

EOD 처리 후 Redis에 저장된 일별/주별 피드백 리포트를 제공한다.
Pending adjustment 목록 및 승인/거절 기능도 포함한다.

라우터 구조:
  - feedback_router: /api/feedback/* (daily, latest — ApiConstants 경로)
  - feedback_compat_router: /feedback/* (weekly, pending, approve/reject — Flutter TODO 경로)
두 라우터를 api_server.py에 모두 등록한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# ApiConstants.feedbackLatest = '/api/feedback/latest' 와 일치하는 접두어를 사용한다
feedback_router = APIRouter(prefix="/api/feedback", tags=["feedback"])

# Flutter가 /api/ 없이 호출하는 경로: /feedback/weekly, /feedback/pending-adjustments 등
feedback_compat_router = APIRouter(prefix="/feedback", tags=["feedback"])

_system: InjectedSystem | None = None


class FeedbackSummary(BaseModel):
    """피드백 요약 항목이다."""

    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_pnl_amount: float = 0.0
    total_pnl_pct: float = 0.0
    best_ticker: str | None = None
    worst_ticker: str | None = None


class FeedbackReportResponse(BaseModel):
    """피드백 리포트 응답 모델이다."""

    period: str
    summary: FeedbackSummary = Field(default_factory=FeedbackSummary)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    adjustments: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""


class PendingAdjustmentsResponse(BaseModel):
    """승인 대기 조정 목록 응답 모델이다."""

    adjustments: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class AdjustmentActionResponse(BaseModel):
    """조정 승인/거절 응답 모델이다."""

    status: str
    adjustment_id: str


def set_feedback_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("FeedbackEndpoints 의존성 주입 완료")


def _empty_report(period: str) -> FeedbackReportResponse:
    """빈 피드백 리포트 기본 구조를 반환한다."""
    return FeedbackReportResponse(
        period=period,
        summary=FeedbackSummary(),
        trades=[],
        adjustments=[],
        message="피드백 데이터가 없다",
    )


def _dict_to_report(data: dict[str, Any], period: str) -> FeedbackReportResponse:
    """캐시된 딕셔너리를 FeedbackReportResponse로 변환한다."""
    raw_summary = data.get("summary", {})
    summary = FeedbackSummary(
        total_trades=raw_summary.get("total_trades", 0),
        win_count=raw_summary.get("win_count", 0),
        loss_count=raw_summary.get("loss_count", 0),
        win_rate=raw_summary.get("win_rate", 0.0),
        total_pnl_amount=raw_summary.get("total_pnl_amount", 0.0),
        total_pnl_pct=raw_summary.get("total_pnl_pct", 0.0),
        best_ticker=raw_summary.get("best_ticker"),
        worst_ticker=raw_summary.get("worst_ticker"),
    )
    return FeedbackReportResponse(
        period=data.get("period", period),
        summary=summary,
        trades=data.get("trades", []),
        adjustments=data.get("adjustments", []),
        message=data.get("message", ""),
    )


@feedback_router.get("/daily/{date}", response_model=FeedbackReportResponse)
async def get_daily_feedback(date: str) -> FeedbackReportResponse:
    """특정 날짜의 일별 피드백 리포트를 반환한다.

    Redis 캐시 키: feedback:{date} (EOD 시퀀스에서 저장)
    date 형식: YYYY-MM-DD
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # EOD 시퀀스는 feedback:{date} 키에 저장한다
        cached = await cache.read_json(f"feedback:{date}")
        if cached and isinstance(cached, dict):
            return _dict_to_report(cached, date)
        # 캐시 미스 시 빈 리포트 반환 (404가 아닌 200 + empty data)
        return _empty_report(date)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 피드백 조회 실패: %s", date)
        raise HTTPException(status_code=500, detail="피드백 조회 실패") from None


@feedback_router.get("/weekly/{week}", response_model=FeedbackReportResponse)
async def get_weekly_feedback(week: str) -> FeedbackReportResponse:
    """특정 주차 피드백 리포트를 반환한다.

    Redis 캐시 키: feedback:weekly:{week}
    week 형식: YYYY-WNN (예: 2026-W09)
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json(f"feedback:weekly:{week}")
        if cached and isinstance(cached, dict):
            return _dict_to_report(cached, week)
        return _empty_report(week)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("주별 피드백 조회 실패: %s", week)
        raise HTTPException(status_code=500, detail="주별 피드백 조회 실패") from None


@feedback_router.get("/latest", response_model=FeedbackReportResponse)
async def get_latest_feedback() -> FeedbackReportResponse:
    """가장 최근 피드백 리포트를 반환한다.

    Redis 캐시 키: feedback:latest (EOD 시퀀스에서 항상 최신으로 덮어씀)
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:latest")
        if cached and isinstance(cached, dict):
            return _dict_to_report(cached, "latest")
        return _empty_report("latest")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("최근 피드백 조회 실패")
        raise HTTPException(status_code=500, detail="최근 피드백 조회 실패") from None


@feedback_router.get("/pending-adjustments", response_model=PendingAdjustmentsResponse)
async def get_pending_adjustments() -> PendingAdjustmentsResponse:
    """승인 대기 중인 전략 조정 목록을 반환한다.

    Redis 캐시 키: feedback:pending_adjustments
    실행 최적화 모듈(ParamTuner)이 EOD에 저장한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:pending_adjustments")
        adjustments = cached if isinstance(cached, list) else []
        return PendingAdjustmentsResponse(adjustments=adjustments, count=len(adjustments))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("Pending 조정 목록 조회 실패")
        raise HTTPException(status_code=500, detail="조정 목록 조회 실패") from None


@feedback_router.post(
    "/approve-adjustment/{adjustment_id}",
    response_model=AdjustmentActionResponse,
)
async def approve_adjustment(
    adjustment_id: str,
    _key: str = Depends(verify_api_key),
) -> AdjustmentActionResponse:
    """전략 조정 항목을 승인한다. 인증 필수.

    승인된 항목은 Redis pending 목록에서 제거하고 applied 목록에 추가한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:pending_adjustments")
        adjustments: list = cached if isinstance(cached, list) else []

        # ID 일치 항목 제거
        remaining = [a for a in adjustments if str(a.get("id", "")) != adjustment_id]
        approved = next(
            (a for a in adjustments if str(a.get("id", "")) == adjustment_id), None
        )

        if approved is None:
            raise HTTPException(
                status_code=404,
                detail=f"조정 항목을 찾을 수 없다: {adjustment_id}",
            )

        # pending 목록 갱신
        await cache.write_json("feedback:pending_adjustments", remaining)

        # applied 목록에 추가
        applied_key = "feedback:applied_adjustments"
        applied = await cache.read_json(applied_key)
        applied_list = applied if isinstance(applied, list) else []
        applied_list.append({**approved, "status": "approved"})
        await cache.write_json(applied_key, applied_list)

        _logger.info("전략 조정 승인 완료: %s", adjustment_id)
        return AdjustmentActionResponse(status="approved", adjustment_id=adjustment_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("전략 조정 승인 실패: %s", adjustment_id)
        raise HTTPException(status_code=500, detail="승인 처리 실패") from None


@feedback_router.post(
    "/reject-adjustment/{adjustment_id}",
    response_model=AdjustmentActionResponse,
)
async def reject_adjustment(
    adjustment_id: str,
    _key: str = Depends(verify_api_key),
) -> AdjustmentActionResponse:
    """전략 조정 항목을 거절한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:pending_adjustments")
        adjustments: list = cached if isinstance(cached, list) else []

        remaining = [a for a in adjustments if str(a.get("id", "")) != adjustment_id]
        rejected = next(
            (a for a in adjustments if str(a.get("id", "")) == adjustment_id), None
        )

        if rejected is None:
            raise HTTPException(
                status_code=404,
                detail=f"조정 항목을 찾을 수 없다: {adjustment_id}",
            )

        await cache.write_json("feedback:pending_adjustments", remaining)
        _logger.info("전략 조정 거절 완료: %s", adjustment_id)
        return AdjustmentActionResponse(status="rejected", adjustment_id=adjustment_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("전략 조정 거절 실패: %s", adjustment_id)
        raise HTTPException(status_code=500, detail="거절 처리 실패") from None


# ── /feedback/* 호환 라우터 (Flutter TODO 경로 — /api/ 없는 버전) ──

@feedback_compat_router.get("/weekly/{week}", response_model=FeedbackReportResponse)
async def get_weekly_feedback_compat(week: str) -> FeedbackReportResponse:
    """주별 피드백 리포트를 반환한다. Flutter /feedback/weekly/{week} 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json(f"feedback:weekly:{week}")
        if cached and isinstance(cached, dict):
            return _dict_to_report(cached, week)
        return _empty_report(week)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("주별 피드백 조회 실패 (compat): %s", week)
        raise HTTPException(status_code=500, detail="주별 피드백 조회 실패") from None


@feedback_compat_router.get(
    "/pending-adjustments",
    response_model=PendingAdjustmentsResponse,
)
async def get_pending_adjustments_compat() -> PendingAdjustmentsResponse:
    """승인 대기 조정 목록을 반환한다. Flutter /feedback/pending-adjustments 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:pending_adjustments")
        adjustments = cached if isinstance(cached, list) else []
        return PendingAdjustmentsResponse(adjustments=adjustments, count=len(adjustments))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("Pending 조정 목록 조회 실패 (compat)")
        raise HTTPException(status_code=500, detail="조정 목록 조회 실패") from None


@feedback_compat_router.post(
    "/approve-adjustment/{adjustment_id}",
    response_model=AdjustmentActionResponse,
)
async def approve_adjustment_compat(
    adjustment_id: str,
    _key: str = Depends(verify_api_key),
) -> AdjustmentActionResponse:
    """전략 조정 항목을 승인한다. Flutter /feedback/approve-adjustment/{id} 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:pending_adjustments")
        adjustments: list = cached if isinstance(cached, list) else []
        remaining = [a for a in adjustments if str(a.get("id", "")) != adjustment_id]
        approved = next(
            (a for a in adjustments if str(a.get("id", "")) == adjustment_id), None
        )
        if approved is None:
            raise HTTPException(
                status_code=404,
                detail=f"조정 항목을 찾을 수 없다: {adjustment_id}",
            )
        await cache.write_json("feedback:pending_adjustments", remaining)
        applied_key = "feedback:applied_adjustments"
        applied = await cache.read_json(applied_key)
        applied_list = applied if isinstance(applied, list) else []
        applied_list.append({**approved, "status": "approved"})
        await cache.write_json(applied_key, applied_list)
        _logger.info("전략 조정 승인 완료 (compat): %s", adjustment_id)
        return AdjustmentActionResponse(status="approved", adjustment_id=adjustment_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("전략 조정 승인 실패 (compat): %s", adjustment_id)
        raise HTTPException(status_code=500, detail="승인 처리 실패") from None


@feedback_compat_router.post(
    "/reject-adjustment/{adjustment_id}",
    response_model=AdjustmentActionResponse,
)
async def reject_adjustment_compat(
    adjustment_id: str,
    _key: str = Depends(verify_api_key),
) -> AdjustmentActionResponse:
    """전략 조정 항목을 거절한다. Flutter /feedback/reject-adjustment/{id} 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:pending_adjustments")
        adjustments: list = cached if isinstance(cached, list) else []
        remaining = [a for a in adjustments if str(a.get("id", "")) != adjustment_id]
        rejected = next(
            (a for a in adjustments if str(a.get("id", "")) == adjustment_id), None
        )
        if rejected is None:
            raise HTTPException(
                status_code=404,
                detail=f"조정 항목을 찾을 수 없다: {adjustment_id}",
            )
        await cache.write_json("feedback:pending_adjustments", remaining)
        _logger.info("전략 조정 거절 완료 (compat): %s", adjustment_id)
        return AdjustmentActionResponse(status="rejected", adjustment_id=adjustment_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("전략 조정 거절 실패 (compat): %s", adjustment_id)
        raise HTTPException(status_code=500, detail="거절 처리 실패") from None
