"""F7.11 TradeReasoningEndpoints -- 매매 근거 조회 API이다.

매매 날짜 목록, 일별 매매 근거, 통계, 피드백 기능을 제공한다.
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

trade_reasoning_router = APIRouter(
    prefix="/api/trade-reasoning",
    tags=["trade-reasoning"],
)

_system: InjectedSystem | None = None


class FeedbackRequest(BaseModel):
    """매매 피드백 요청 모델이다.

    Flutter는 {feedback, rating, notes}를 보내고 기존 백엔드는 {rating, comment}를 기대한다.
    두 형식 모두 호환한다.
    """

    rating: int  # 1~5
    comment: str = ""
    feedback: str = ""
    notes: str = ""


class TradeDatesResponse(BaseModel):
    """매매 날짜 목록 응답 모델이다."""

    dates: list[str] = Field(default_factory=list)


class DailyReasoningResponse(BaseModel):
    """일별 매매 근거 응답 모델이다."""

    date: str
    trades: list[dict[str, Any]] = Field(default_factory=list)


class TradeStatsResponse(BaseModel):
    """매매 통계 응답 모델이다."""

    total_trades: int = 0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    best_trade: dict[str, Any] | None = None
    worst_trade: dict[str, Any] | None = None
    message: str = ""


class TradeFeedbackResponse(BaseModel):
    """매매 피드백 저장 응답 모델이다."""

    status: str
    trade_id: str


def set_trade_reasoning_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("TradeReasoningEndpoints 의존성 주입 완료")


@trade_reasoning_router.get("/dates", response_model=TradeDatesResponse)
async def get_trade_dates() -> TradeDatesResponse:
    """매매가 존재하는 날짜 목록을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("trades:dates")
        dates = cached if isinstance(cached, list) else []
        return TradeDatesResponse(dates=dates)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 날짜 조회 실패")
        raise HTTPException(status_code=500, detail="날짜 조회 실패") from None


@trade_reasoning_router.get("/daily", response_model=DailyReasoningResponse)
async def get_daily_reasoning(
    date: str = "",
) -> DailyReasoningResponse:
    """일별 매매 근거를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        key = f"trades:reasoning:{date}" if date else "trades:reasoning:latest"
        cached = await cache.read_json(key)
        trades = cached if isinstance(cached, list) else []
        return DailyReasoningResponse(date=date or "latest", trades=trades)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 매매 근거 조회 실패: %s", date)
        raise HTTPException(status_code=500, detail="근거 조회 실패") from None


@trade_reasoning_router.get("/stats", response_model=TradeStatsResponse)
async def get_trade_stats() -> TradeStatsResponse:
    """매매 통계를 반환한다. 승률, 평균 수익 등이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("trades:stats")
        if cached and isinstance(cached, dict):
            return TradeStatsResponse(
                total_trades=cached.get("total_trades", 0),
                win_rate=cached.get("win_rate", 0.0),
                avg_profit=cached.get("avg_profit", 0.0),
                avg_loss=cached.get("avg_loss", 0.0),
                best_trade=cached.get("best_trade"),
                worst_trade=cached.get("worst_trade"),
                message=cached.get("message", ""),
            )
        return TradeStatsResponse(message="통계 데이터가 없다")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 통계 조회 실패")
        raise HTTPException(status_code=500, detail="통계 조회 실패") from None


@trade_reasoning_router.post(
    "/{trade_id}/feedback",
    response_model=TradeFeedbackResponse,
)
async def submit_feedback(
    trade_id: str,
    req: FeedbackRequest,
    _key: str = Depends(verify_api_key),
) -> TradeFeedbackResponse:
    """매매에 대한 피드백을 저장한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        if not 1 <= req.rating <= 5:
            raise HTTPException(
                status_code=422,
                detail="rating은 1~5 범위여야 한다",
            )
        cache = _system.components.cache
        # Flutter는 feedback 필드, 기존은 comment 필드를 사용한다
        comment_text = req.comment or req.feedback
        feedback = {
            "trade_id": trade_id,
            "rating": req.rating,
            "comment": comment_text,
            "notes": req.notes,
        }
        await cache.write_json(f"trades:feedback:{trade_id}", feedback)
        _logger.info("매매 피드백 저장: trade_id=%s, rating=%d", trade_id, req.rating)
        return TradeFeedbackResponse(status="saved", trade_id=trade_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 피드백 저장 실패: %s", trade_id)
        raise HTTPException(status_code=500, detail="피드백 저장 실패") from None


@trade_reasoning_router.put(
    "/{trade_id}/feedback",
    response_model=TradeFeedbackResponse,
)
async def put_trade_feedback(
    trade_id: str,
    req: FeedbackRequest,
    _key: str = Depends(verify_api_key),
) -> TradeFeedbackResponse:
    """PUT 메서드로 매매 피드백을 저장한다. Flutter 호환 별칭이다."""
    return await submit_feedback(trade_id, req, _key=_key)
