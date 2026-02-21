"""
Flutter 대시보드용 거래 결정 근거(Trade Reasoning) API 엔드포인트.

각 거래의 AI 분석 근거, 신호, 시장 레짐, 승인 대기 피드백 등을
조회하고 주석을 달 수 있는 기능을 제공한다.

엔드포인트 목록:
  GET  /api/trade-reasoning/dates          - 거래가 존재하는 날짜 목록
  GET  /api/trade-reasoning/daily          - 특정 날짜의 전체 거래 + 근거
  GET  /api/trade-reasoning/stats          - 일별 거래 통계 요약
  PUT  /api/trade-reasoning/{trade_id}/feedback - 거래에 사용자 피드백 추가
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import DATE

from src.db.connection import get_session
from src.db.models import Trade
from src.monitoring.auth import verify_api_key
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 라우터 정의
# ---------------------------------------------------------------------------

trade_reasoning_router = APIRouter(
    prefix="/api/trade-reasoning",
    tags=["Trade Reasoning"],
)


# ---------------------------------------------------------------------------
# 요청 / 응답 스키마
# ---------------------------------------------------------------------------


class TradeDateEntry(BaseModel):
    """날짜별 거래 건수 응답 스키마."""

    date: str = Field(..., description="YYYY-MM-DD 형식의 날짜")
    trade_count: int = Field(..., description="해당 날짜의 거래 건수")


class TradeDatesResponse(BaseModel):
    """거래 날짜 목록 응답 스키마."""

    dates: list[TradeDateEntry]
    total_days: int


class ReasoningDetail(BaseModel):
    """AI 분석 근거 상세 정보 스키마."""

    summary: str | None = Field(None, description="ai_signals의 첫 번째 reason 요약")
    indicator_direction: str | None = Field(None, description="지표 방향 (bullish/bearish 등)")
    indicator_confidence: float | None = Field(None, description="지표 신뢰도 0.0~1.0")
    signals: list[Any] = Field(default_factory=list, description="전체 ai_signals 리스트")


class TradeReasoningItem(BaseModel):
    """개별 거래 + AI 근거 응답 스키마."""

    id: str
    ticker: str
    direction: str
    action: str = Field(..., description="buy / sell (direction에서 유추)")
    entry_price: float
    exit_price: float | None
    entry_at: str
    exit_at: str | None
    pnl_pct: float | None
    pnl_amount: float | None
    hold_minutes: int | None
    status: str = Field(..., description="open 또는 closed")

    # AI 근거 섹션
    ai_confidence: float | None
    market_regime: str | None
    reasoning: ReasoningDetail
    exit_reason: str | None
    post_analysis: dict[str, Any]


class DailyTradesResponse(BaseModel):
    """일별 거래 전체 목록 응답 스키마."""

    date: str
    trades: list[TradeReasoningItem]
    total_count: int


class DailyStatsResponse(BaseModel):
    """일별 거래 통계 요약 응답 스키마."""

    date: str
    total_trades: int
    win_count: int
    loss_count: int
    breakeven_count: int
    total_pnl_amount: float
    total_pnl_pct: float
    win_rate: float
    most_common_regime: str | None
    avg_confidence_winners: float | None
    avg_confidence_losers: float | None
    top_tickers: list[dict[str, Any]]


class FeedbackRequest(BaseModel):
    """거래 피드백 요청 스키마."""

    feedback: str = Field(..., min_length=1, max_length=2000, description="피드백 내용")
    rating: int = Field(..., ge=1, le=5, description="평점 1~5")
    notes: str | None = Field(None, max_length=2000, description="추가 메모")


class FeedbackResponse(BaseModel):
    """거래 피드백 응답 스키마."""

    trade_id: str
    post_analysis: dict[str, Any]
    message: str


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _parse_date_param(date_str: str | None) -> date:
    """날짜 문자열을 파싱한다. None이면 오늘 UTC 날짜를 반환한다."""
    if date_str is None:
        return datetime.now(tz=timezone.utc).date()
    try:
        return date.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요. 입력값: {date_str}",
        ) from exc


def _build_utc_range(target_date: date) -> tuple[datetime, datetime]:
    """주어진 날짜의 UTC 시작~종료 datetime 범위를 반환한다."""
    start = datetime(
        target_date.year, target_date.month, target_date.day,
        0, 0, 0, tzinfo=timezone.utc,
    )
    end = start + timedelta(days=1)
    return start, end


def _infer_action(direction: str) -> str:
    """포지션 방향으로 매수/매도 액션을 유추한다."""
    return "sell" if direction.lower() in ("short", "sell") else "buy"


def _extract_reasoning(ai_signals: list[Any]) -> ReasoningDetail:
    """ai_signals 리스트에서 근거 요약을 추출한다."""
    if not ai_signals:
        return ReasoningDetail(signals=[])

    first = ai_signals[0] if isinstance(ai_signals[0], dict) else {}
    return ReasoningDetail(
        summary=first.get("reason"),
        indicator_direction=first.get("indicator_direction"),
        indicator_confidence=first.get("indicator_confidence"),
        signals=ai_signals,
    )


def _trade_to_item(trade: Trade) -> TradeReasoningItem:
    """Trade ORM 객체를 TradeReasoningItem 응답 스키마로 변환한다."""
    signals: list[Any] = trade.ai_signals or []
    return TradeReasoningItem(
        id=str(trade.id),
        ticker=trade.ticker,
        direction=trade.direction,
        action=_infer_action(trade.direction),
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        entry_at=trade.entry_at.isoformat(),
        exit_at=trade.exit_at.isoformat() if trade.exit_at else None,
        pnl_pct=trade.pnl_pct,
        pnl_amount=trade.pnl_amount,
        hold_minutes=trade.hold_minutes,
        status="closed" if trade.exit_at is not None else "open",
        ai_confidence=trade.ai_confidence,
        market_regime=trade.market_regime,
        reasoning=_extract_reasoning(signals),
        exit_reason=trade.exit_reason,
        post_analysis=trade.post_analysis or {},
    )


# ---------------------------------------------------------------------------
# 엔드포인트: GET /api/trade-reasoning/dates
# ---------------------------------------------------------------------------


@trade_reasoning_router.get(
    "/dates",
    response_model=TradeDatesResponse,
    summary="거래 날짜 목록 조회",
    description="거래가 존재하는 날짜 목록을 최신 순으로 반환한다.",
)
async def list_trade_dates() -> TradeDatesResponse:
    """거래 테이블을 날짜별로 그룹화하여 거래가 있는 날짜와 건수를 반환한다.

    Returns:
        TradeDatesResponse: 날짜 목록과 각 날짜의 거래 건수.

    Raises:
        HTTPException: DB 조회 오류 시 500을 반환한다.
    """
    try:
        async with get_session() as session:
            stmt = (
                select(
                    cast(Trade.entry_at, DATE).label("trade_date"),
                    func.count(Trade.id).label("trade_count"),
                )
                .group_by(cast(Trade.entry_at, DATE))
                .order_by(cast(Trade.entry_at, DATE).desc())
            )
            result = await session.execute(stmt)
            rows = result.all()

        entries = [
            TradeDateEntry(
                date=str(row.trade_date),
                trade_count=row.trade_count,
            )
            for row in rows
        ]
        return TradeDatesResponse(dates=entries, total_days=len(entries))

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("거래 날짜 목록 조회 실패: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="거래 날짜 목록을 조회하는 중 오류가 발생했습니다.",
        ) from exc


# ---------------------------------------------------------------------------
# 엔드포인트: GET /api/trade-reasoning/daily
# ---------------------------------------------------------------------------


@trade_reasoning_router.get(
    "/daily",
    response_model=DailyTradesResponse,
    summary="일별 거래 + AI 근거 조회",
    description="특정 날짜(UTC)에 진입한 모든 거래와 AI 분석 근거를 반환한다.",
)
async def get_daily_trades(
    date: str | None = Query(None, description="조회 날짜 (YYYY-MM-DD). 미입력 시 오늘 UTC"),
) -> DailyTradesResponse:
    """지정된 날짜 범위 내의 거래를 진입 시각 오름차순으로 조회한다.

    Args:
        date: 조회할 날짜 문자열 (YYYY-MM-DD). None이면 오늘 UTC 날짜.

    Returns:
        DailyTradesResponse: 해당 날짜의 거래 목록 + AI 근거.

    Raises:
        HTTPException: 날짜 형식 오류(400) 또는 DB 조회 오류(500).
    """
    target_date = _parse_date_param(date)
    start_dt, end_dt = _build_utc_range(target_date)

    try:
        async with get_session() as session:
            stmt = (
                select(Trade)
                .where(Trade.entry_at >= start_dt)
                .where(Trade.entry_at < end_dt)
                .order_by(Trade.entry_at.asc())
            )
            result = await session.execute(stmt)
            trades = result.scalars().all()

        items = [_trade_to_item(t) for t in trades]
        return DailyTradesResponse(
            date=str(target_date),
            trades=items,
            total_count=len(items),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "일별 거래 조회 실패 (date=%s): %s", target_date, exc, exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="일별 거래를 조회하는 중 오류가 발생했습니다.",
        ) from exc


# ---------------------------------------------------------------------------
# 엔드포인트: GET /api/trade-reasoning/stats
# ---------------------------------------------------------------------------


@trade_reasoning_router.get(
    "/stats",
    response_model=DailyStatsResponse,
    summary="일별 거래 통계 조회",
    description="특정 날짜의 거래 통계 요약(승패, PnL, 레짐, 신뢰도)을 반환한다.",
)
async def get_daily_stats(
    date: str | None = Query(None, description="조회 날짜 (YYYY-MM-DD). 미입력 시 오늘 UTC"),
) -> DailyStatsResponse:
    """지정된 날짜의 거래를 집계하여 통계 요약을 반환한다.

    Args:
        date: 조회할 날짜 문자열 (YYYY-MM-DD). None이면 오늘 UTC 날짜.

    Returns:
        DailyStatsResponse: 거래 통계 (승/패, PnL 합계, 레짐, 신뢰도 등).

    Raises:
        HTTPException: 날짜 형식 오류(400) 또는 DB 조회 오류(500).
    """
    target_date = _parse_date_param(date)
    start_dt, end_dt = _build_utc_range(target_date)

    try:
        async with get_session() as session:
            stmt = (
                select(Trade)
                .where(Trade.entry_at >= start_dt)
                .where(Trade.entry_at < end_dt)
            )
            result = await session.execute(stmt)
            trades = result.scalars().all()

        # 기본 집계
        total = len(trades)
        win_count = 0
        loss_count = 0
        breakeven_count = 0
        total_pnl_amount = 0.0
        pnl_pct_values: list[float] = []
        regimes: list[str] = []
        confidence_winners: list[float] = []
        confidence_losers: list[float] = []
        ticker_counter: Counter[str] = Counter()

        for t in trades:
            pnl = t.pnl_amount or 0.0
            pnl_pct = t.pnl_pct or 0.0
            total_pnl_amount += pnl
            # pnl_pct는 단순 합산이 아닌 가중 평균으로 계산하기 위해 목록에 수집한다.
            pnl_pct_values.append(pnl_pct)
            ticker_counter[t.ticker] += 1

            if t.market_regime:
                regimes.append(t.market_regime)

            if pnl > 0:
                win_count += 1
                if t.ai_confidence is not None:
                    confidence_winners.append(t.ai_confidence)
            elif pnl < 0:
                loss_count += 1
                if t.ai_confidence is not None:
                    confidence_losers.append(t.ai_confidence)
            else:
                breakeven_count += 1

        # total_pnl_pct: 단순 합산 대신 평균 수익률을 사용한다.
        # 개별 거래 규모(포지션 크기)가 pnl_pct에 미반영되므로 산술 평균으로 대체한다.
        total_pnl_pct = (
            sum(pnl_pct_values) / len(pnl_pct_values) if pnl_pct_values else 0.0
        )

        # 가장 흔한 레짐
        most_common_regime: str | None = None
        if regimes:
            regime_counter = Counter(regimes)
            most_common_regime = regime_counter.most_common(1)[0][0]

        # 평균 신뢰도
        avg_conf_winners = (
            sum(confidence_winners) / len(confidence_winners) if confidence_winners else None
        )
        avg_conf_losers = (
            sum(confidence_losers) / len(confidence_losers) if confidence_losers else None
        )

        # 승률
        win_rate = (win_count / total) if total > 0 else 0.0

        # 상위 거래 티커
        top_tickers = [
            {"ticker": ticker, "count": count}
            for ticker, count in ticker_counter.most_common(5)
        ]

        return DailyStatsResponse(
            date=str(target_date),
            total_trades=total,
            win_count=win_count,
            loss_count=loss_count,
            breakeven_count=breakeven_count,
            total_pnl_amount=round(total_pnl_amount, 4),
            total_pnl_pct=round(total_pnl_pct, 4),
            win_rate=round(win_rate, 4),
            most_common_regime=most_common_regime,
            avg_confidence_winners=(
                round(avg_conf_winners, 4) if avg_conf_winners is not None else None
            ),
            avg_confidence_losers=(
                round(avg_conf_losers, 4) if avg_conf_losers is not None else None
            ),
            top_tickers=top_tickers,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "일별 거래 통계 조회 실패 (date=%s): %s", target_date, exc, exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="일별 거래 통계를 조회하는 중 오류가 발생했습니다.",
        ) from exc


# ---------------------------------------------------------------------------
# 엔드포인트: PUT /api/trade-reasoning/{trade_id}/feedback
# ---------------------------------------------------------------------------


@trade_reasoning_router.put(
    "/{trade_id}/feedback",
    response_model=FeedbackResponse,
    summary="거래 피드백 추가",
    description="특정 거래의 post_analysis JSONB 필드에 사용자 피드백을 추가한다.",
)
async def add_trade_feedback(
    trade_id: str,
    body: FeedbackRequest,
    _: None = Depends(verify_api_key),
) -> FeedbackResponse:
    """거래의 post_analysis 필드에 사용자 피드백(내용, 평점, 메모)을 저장한다.

    기존 post_analysis 내용은 유지하며 'user_feedback' 키에 덮어쓴다.

    Args:
        trade_id: 피드백을 추가할 거래 UUID.
        body: 피드백 요청 본문 (feedback, rating, notes).

    Returns:
        FeedbackResponse: 업데이트된 post_analysis 전체 내용.

    Raises:
        HTTPException: 거래가 없는 경우 404, DB 오류 시 500.
    """
    try:
        async with get_session() as session:
            stmt = select(Trade).where(Trade.id == trade_id)
            result = await session.execute(stmt)
            trade = result.scalar_one_or_none()

            if trade is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"trade_id='{trade_id}'에 해당하는 거래를 찾을 수 없습니다.",
                )

            # 기존 post_analysis 유지 + user_feedback 갱신
            current_analysis: dict[str, Any] = trade.post_analysis or {}
            current_analysis["user_feedback"] = {
                "feedback": body.feedback,
                "rating": body.rating,
                "notes": body.notes,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            trade.post_analysis = current_analysis

            # SQLAlchemy JSONB 변경 감지를 위해 명시적으로 flag_modified 호출
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(trade, "post_analysis")

            await session.flush()

        logger.info("거래 피드백 저장 완료: trade_id=%s, rating=%d", trade_id, body.rating)
        return FeedbackResponse(
            trade_id=trade_id,
            post_analysis=current_analysis,
            message="피드백이 성공적으로 저장되었습니다.",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "거래 피드백 저장 실패 (trade_id=%s): %s", trade_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="거래 피드백을 저장하는 중 오류가 발생했습니다.",
        ) from exc
