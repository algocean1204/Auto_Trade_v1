"""F7.24 FeedbackEndpoints -- 피드백/리포트 조회 API이다.

EOD 처리 후 캐시에 저장된 일별/주별 피드백 리포트를 제공한다.
Pending adjustment 목록 및 승인/거절 기능도 포함한다.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.common.logger import get_logger
from src.db.models import FeedbackReport
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# ApiConstants.feedbackLatest = '/api/feedback/latest' 와 일치하는 접두어를 사용한다
feedback_router = APIRouter(prefix="/api/feedback", tags=["feedback"])

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


async def _load_feedback_from_db(date: str) -> dict[str, Any] | None:
    """DB feedback_reports 테이블에서 피드백 데이터를 로드한다."""
    if _system is None:
        return None
    try:
        db = _system.components.db
        async with db.get_session() as session:
            stmt = (
                select(FeedbackReport)
                .where(FeedbackReport.report_date == date)
                .order_by(FeedbackReport.report_type.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row and row.content:
                content = row.content
                if isinstance(content, str):
                    content = json.loads(content)
                return content if isinstance(content, dict) else None
    except Exception:
        _logger.warning("DB에서 피드백 조회 실패: %s", date)
    return None


async def _load_latest_feedback_from_db() -> tuple[dict[str, Any] | None, str]:
    """DB에서 가장 최근 피드백 리포트를 로드한다. (데이터, 날짜) 튜플을 반환한다."""
    if _system is None:
        return None, "latest"
    try:
        db = _system.components.db
        async with db.get_session() as session:
            stmt = (
                select(FeedbackReport)
                .order_by(FeedbackReport.report_date.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row and row.content:
                content = row.content
                if isinstance(content, str):
                    content = json.loads(content)
                date_str = str(row.report_date) if row.report_date else "latest"
                return content if isinstance(content, dict) else None, date_str
    except Exception:
        _logger.warning("DB에서 최신 피드백 조회 실패")
    return None, "latest"


def _dict_to_report(data: dict[str, Any], period: str) -> FeedbackReportResponse:
    """캐시된 딕셔너리를 FeedbackReportResponse로 변환한다."""
    raw_summary = data.get("summary", {})
    # AI 피드백은 win_rate/total_trades만 제공하므로 win_count/loss_count를 파생한다
    total_trades = raw_summary.get("total_trades", 0)
    win_rate = raw_summary.get("win_rate", 0.0)
    explicit_win = raw_summary.get("win_count", 0)
    derived_win = round(win_rate / 100 * total_trades) if total_trades > 0 else 0
    win_count = explicit_win if explicit_win > 0 else derived_win
    loss_count = raw_summary.get("loss_count", 0)
    if loss_count == 0 and total_trades > 0:
        loss_count = total_trades - win_count
    # AI는 best_trade/worst_trade 키를 사용하므로 fallback으로 읽는다
    best_ticker = raw_summary.get("best_ticker") or raw_summary.get("best_trade")
    worst_ticker = raw_summary.get("worst_ticker") or raw_summary.get("worst_trade")
    summary = FeedbackSummary(
        total_trades=total_trades,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        total_pnl_amount=raw_summary.get("total_pnl_amount", 0.0),
        total_pnl_pct=raw_summary.get("total_pnl_pct", 0.0),
        best_ticker=best_ticker,
        worst_ticker=worst_ticker,
    )
    return FeedbackReportResponse(
        period=data.get("period", period),
        summary=summary,
        trades=data.get("trades", []),
        adjustments=data.get("adjustments", []),
        message=data.get("message", ""),
    )


@feedback_router.get("/daily/{date}", response_model=FeedbackReportResponse)
async def get_daily_feedback(
    date: str,
    _auth: str = Depends(verify_api_key),
) -> FeedbackReportResponse:
    """특정 날짜의 일별 피드백 리포트를 반환한다.

    캐시 키: feedback:{date} (EOD 시퀀스에서 저장)
    date 형식: YYYY-MM-DD
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    # 날짜 형식 검증: YYYY-MM-DD 패턴이어야 한다
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=422, detail="날짜 형식은 YYYY-MM-DD여야 한다")
    try:
        cache = _system.components.cache
        # EOD 시퀀스는 feedback:{date} 키에 저장한다
        cached = await cache.read_json(f"feedback:{date}")
        if cached and isinstance(cached, dict):
            return _dict_to_report(cached, date)
        # 캐시 미스 시 DB fallback 조회
        db_data = await _load_feedback_from_db(date)
        if db_data:
            return _dict_to_report(db_data, date)
        return _empty_report(date)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 피드백 조회 실패: %s", date)
        raise HTTPException(status_code=500, detail="피드백 조회 실패") from None


@feedback_router.get("/weekly/{week}", response_model=FeedbackReportResponse)
async def get_weekly_feedback(
    week: str,
    _auth: str = Depends(verify_api_key),
) -> FeedbackReportResponse:
    """특정 주차 피드백 리포트를 반환한다.

    캐시 키: feedback:weekly:{week}
    week 형식: YYYY-WNN (예: 2026-W09)
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    # 주차 형식 검증: YYYY-WNN 패턴이어야 한다
    if not re.match(r"^\d{4}-W\d{2}$", week):
        raise HTTPException(status_code=422, detail="주차 형식은 YYYY-WNN이어야 한다 (예: 2026-W09)")
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
async def get_latest_feedback(
    _auth: str = Depends(verify_api_key),
) -> FeedbackReportResponse:
    """가장 최근 피드백 리포트를 반환한다.

    캐시 키: feedback:latest (EOD 시퀀스에서 항상 최신으로 덮어씀)
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("feedback:latest")
        if cached and isinstance(cached, dict):
            return _dict_to_report(cached, "latest")
        # 캐시 미스 시 DB에서 가장 최근 피드백 조회
        db_data, db_date = await _load_latest_feedback_from_db()
        if db_data:
            return _dict_to_report(db_data, db_date)
        return _empty_report("latest")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("최근 피드백 조회 실패")
        raise HTTPException(status_code=500, detail="최근 피드백 조회 실패") from None


@feedback_router.get("/pending-adjustments", response_model=PendingAdjustmentsResponse)
async def get_pending_adjustments(
    _auth: str = Depends(verify_api_key),
) -> PendingAdjustmentsResponse:
    """승인 대기 중인 전략 조정 목록을 반환한다.

    캐시 키: feedback:pending_adjustments
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
    adjustment_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    _key: str = Depends(verify_api_key),
) -> AdjustmentActionResponse:
    """전략 조정 항목을 승인한다. 인증 필수.

    승인된 항목은 캐시 pending 목록에서 제거하고 applied 목록에 추가한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache

        # 원자적으로 pending 목록에서 해당 ID 항목을 제거한다 (경합 조건 방지)
        approved = await cache.atomic_list_remove(
            "feedback:pending_adjustments",
            predicate_key="id",
            predicate_value=adjustment_id,
        )

        if approved is None:
            raise HTTPException(
                status_code=404,
                detail=f"조정 항목을 찾을 수 없다: {adjustment_id}",
            )

        # applied 목록에 원자적으로 추가한다
        await cache.atomic_list_append(
            "feedback:applied_adjustments",
            [{**approved, "status": "approved"}],
            max_size=1000,
        )

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
    adjustment_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    _key: str = Depends(verify_api_key),
) -> AdjustmentActionResponse:
    """전략 조정 항목을 거절한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache

        # 원자적으로 pending 목록에서 해당 ID 항목을 제거한다 (경합 조건 방지)
        rejected = await cache.atomic_list_remove(
            "feedback:pending_adjustments",
            predicate_key="id",
            predicate_value=adjustment_id,
        )

        if rejected is None:
            raise HTTPException(
                status_code=404,
                detail=f"조정 항목을 찾을 수 없다: {adjustment_id}",
            )

        _logger.info("전략 조정 거절 완료: %s", adjustment_id)
        return AdjustmentActionResponse(status="rejected", adjustment_id=adjustment_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("전략 조정 거절 실패: %s", adjustment_id)
        raise HTTPException(status_code=500, detail="거절 처리 실패") from None
