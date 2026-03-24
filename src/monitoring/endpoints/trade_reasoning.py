"""F7.11 TradeReasoningEndpoints -- 매매 근거 조회 API이다.

매매 날짜 목록, 일별 매매 근거, 통계, 피드백 기능을 제공한다.
캐시 미스 시 DB(Trade 테이블)에서 폴백한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.common.logger import get_logger
from src.db.models import Trade
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

    rating: int = Field(..., ge=1, le=5)  # 1~5
    comment: str = ""
    feedback: str = ""
    notes: str = ""


class TradeDateItem(BaseModel):
    """개별 매매 날짜 + 거래 수 모델이다. Dart TradeReasoningDate.fromJson()과 매핑된다."""

    date: str
    trade_count: int = 0


class TradeDatesResponse(BaseModel):
    """매매 날짜 목록 응답 모델이다. Dart는 dates 내부에 {date, trade_count} 객체를 기대한다."""

    dates: list[TradeDateItem] = Field(default_factory=list)


class DailyReasoningResponse(BaseModel):
    """일별 매매 근거 응답 모델이다."""

    date: str
    trades: list[dict[str, Any]] = Field(default_factory=list)


class TickerCount(BaseModel):
    """티커별 거래 횟수 모델이다."""

    ticker: str
    count: int = 0


class TradeStatsResponse(BaseModel):
    """매매 통계 응답 모델이다. Dart TradeReasoningStats.fromJson()과 매핑된다."""

    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_pnl_amount: float = 0.0
    avg_confidence_winners: float = 0.0
    avg_confidence_losers: float = 0.0
    top_tickers: list[TickerCount] = Field(default_factory=list)
    most_common_regime: str | None = None


class TradeFeedbackResponse(BaseModel):
    """매매 피드백 저장 응답 모델이다."""

    status: str
    trade_id: str


def _normalize_trade(record: dict[str, Any]) -> dict[str, Any]:
    """원시 거래 레코드를 Dart 호환 필드로 정규화한다.

    trades:today 캐시와 trades:reasoning:{date} 캐시 모두에서
    동일한 구조로 반환하기 위해 키를 매핑한다.
    """
    out = dict(record)

    # side → action 변환 (Dart는 action 키를 기대한다)
    if "side" in out and "action" not in out:
        out["action"] = out["side"]

    # price → entry_price 매핑 (원본도 유지한다)
    if "price" in out and "entry_price" not in out:
        out["entry_price"] = out["price"]

    # timestamp → entry_at 매핑 (원본도 유지한다)
    if "timestamp" in out and "entry_at" not in out:
        out["entry_at"] = out["timestamp"]

    # exit_type → exit_reason 매핑 (원본도 유지한다)
    if "exit_type" in out and "exit_reason" not in out:
        out["exit_reason"] = out["exit_type"]

    # id가 없으면 ticker-timestamp 조합으로 생성한다
    if "id" not in out:
        ticker = out.get("ticker", "")
        ts = out.get("timestamp", "")
        out["id"] = f"{ticker}-{ts}" if ticker or ts else str(id(out))

    # pnl_pct 기본값: entry_price와 quantity로 퍼센트를 역산한다
    if "pnl_pct" not in out:
        pnl_amount = out.get("pnl_amount")
        entry_price = out.get("entry_price") or out.get("price")
        qty = out.get("quantity")
        if (
            pnl_amount is not None
            and entry_price is not None
            and qty is not None
        ):
            cost_basis = float(entry_price) * float(qty)
            if abs(cost_basis) > 1e-9:
                out["pnl_pct"] = (float(pnl_amount) / cost_basis) * 100.0
            else:
                out["pnl_pct"] = 0.0
        else:
            out["pnl_pct"] = 0.0

    out.setdefault("reason", "")

    return out


def set_trade_reasoning_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("TradeReasoningEndpoints 의존성 주입 완료")


@trade_reasoning_router.get("/dates", response_model=TradeDatesResponse)
async def get_trade_dates(
    _auth: str = Depends(verify_api_key),
) -> TradeDatesResponse:
    """매매가 존재하는 날짜 목록을 반환한다.

    trades:dates 키를 우선 조회하고, 없으면 trades:today에서 오늘 날짜를 추출한다.
    Dart TradeReasoningDate.fromJson()이 {date, trade_count} 구조를 기대한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache

        # 1차: trades:dates 키에서 날짜 목록을 읽는다
        cached = await cache.read_json("trades:dates")
        raw_dates: list[str] = cached if isinstance(cached, list) else []

        # N+1 캐시 조회를 방지하기 위해 최근 90일분만 조회한다
        _MAX_TRADE_DATES = 90
        date_items: list[TradeDateItem] = []
        for d in raw_dates[:_MAX_TRADE_DATES]:
            if not isinstance(d, str):
                continue
            trades_data = await cache.read_json(f"trades:reasoning:{d}")
            count = len(trades_data) if isinstance(trades_data, list) else 0
            date_items.append(TradeDateItem(date=d, trade_count=count))

        # 2차: trades:dates가 비어있으면 trades:today에서 오늘 거래를 추출한다
        if not date_items:
            today_trades = await cache.read_json("trades:today")
            if today_trades and isinstance(today_trades, list) and len(today_trades) > 0:
                from collections import Counter
                date_counter: Counter[str] = Counter()
                for t in today_trades:
                    if isinstance(t, dict):
                        ts = str(t.get("timestamp", ""))
                        date_str = ts[:10] if len(ts) >= 10 else ""
                        if date_str:
                            date_counter[date_str] += 1
                for d_str, cnt in sorted(date_counter.items(), reverse=True):
                    date_items.append(TradeDateItem(date=d_str, trade_count=cnt))

        return TradeDatesResponse(dates=date_items)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 날짜 조회 실패")
        raise HTTPException(status_code=500, detail="날짜 조회 실패") from None


@trade_reasoning_router.get("/daily", response_model=DailyReasoningResponse)
async def get_daily_reasoning(
    date: str = "",
    _auth: str = Depends(verify_api_key),
) -> DailyReasoningResponse:
    """일별 매매 근거를 반환한다.

    trades:reasoning:{date} 키를 우선 조회하고, 없으면 trades:today에서
    해당 날짜 거래를 필터링하여 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache

        # 1차: trades:reasoning:{date} 키에서 읽는다
        key = f"trades:reasoning:{date}" if date else "trades:reasoning:latest"
        cached = await cache.read_json(key)
        raw_trades = cached if isinstance(cached, list) else []

        # reasoning 캐시 데이터도 정규화한다
        trades = [_normalize_trade(t) for t in raw_trades if isinstance(t, dict)]

        # 2차: 비어있으면 trades:today에서 해당 날짜 거래를 필터링한다
        if not trades:
            today_trades = await cache.read_json("trades:today")
            if today_trades and isinstance(today_trades, list):
                for t in today_trades:
                    if not isinstance(t, dict):
                        continue
                    ts = str(t.get("timestamp", ""))
                    t_date = ts[:10] if len(ts) >= 10 else ""
                    # 날짜 미지정이거나 일치하면 포함한다
                    if not date or t_date == date:
                        trades.append(_normalize_trade(t))

        return DailyReasoningResponse(date=date or "latest", trades=trades)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 매매 근거 조회 실패: %s", date)
        raise HTTPException(status_code=500, detail="근거 조회 실패") from None


@trade_reasoning_router.get("/stats", response_model=TradeStatsResponse)
async def get_trade_stats(
    date: str = "",
    _auth: str = Depends(verify_api_key),
) -> TradeStatsResponse:
    """매매 통계를 반환한다.

    trades:reasoning:{date} 키를 우선 조회하고, 없으면 trades:today에서 계산한다.
    Dart TradeReasoningStats.fromJson()이 기대하는 구조로 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache

        # 1차: trades:reasoning:{date} 키에서 읽는다
        key = f"trades:reasoning:{date}" if date else "trades:reasoning:latest"
        trades_raw = await cache.read_json(key)
        trades: list[dict] = [
            _normalize_trade(t) for t in (trades_raw if isinstance(trades_raw, list) else [])
            if isinstance(t, dict)
        ]

        # 2차: 비어있으면 trades:today에서 해당 날짜 거래를 필터링한다
        if not trades:
            today_raw = await cache.read_json("trades:today")
            if today_raw and isinstance(today_raw, list):
                for t in today_raw:
                    if not isinstance(t, dict):
                        continue
                    ts = str(t.get("timestamp", ""))
                    t_date = ts[:10] if len(ts) >= 10 else ""
                    if not date or t_date == date:
                        converted = _normalize_trade(t)
                        # pnl_pct 역산: avg = price - pnl/qty, pnl_pct = pnl/(avg*qty)*100
                        pnl = converted.get("pnl")
                        price = converted.get("price", 0)
                        qty = converted.get("quantity", 0)
                        if pnl is not None and price > 0 and qty > 0:
                            cost_basis = float(price) * float(qty) - float(pnl)
                            converted["pnl_pct"] = (float(pnl) / cost_basis) * 100.0 if abs(cost_basis) > 1e-9 else 0.0
                        converted.setdefault("pnl_amount", float(pnl) if pnl is not None else 0.0)
                        trades.append(converted)

        return _compute_stats(trades)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 통계 조회 실패")
        raise HTTPException(status_code=500, detail="통계 조회 실패") from None


def _compute_stats(trades: list[dict]) -> TradeStatsResponse:
    """거래 목록에서 Dart 호환 통계를 계산한다."""
    from collections import Counter

    if not trades:
        return TradeStatsResponse()

    total = len(trades)
    win_count = 0
    loss_count = 0
    total_pnl = 0.0
    winner_confidences: list[float] = []
    loser_confidences: list[float] = []
    ticker_counter: Counter[str] = Counter()
    regime_counter: Counter[str] = Counter()

    for t in trades:
        if not isinstance(t, dict):
            continue

        pnl = float(t.get("pnl_pct", 0.0) or 0.0)
        pnl_amount = float(t.get("pnl_amount", 0.0) or 0.0)
        confidence = t.get("ai_confidence")
        ticker = t.get("ticker", "")
        regime = t.get("market_regime")

        total_pnl += pnl_amount

        if pnl >= 0:
            win_count += 1
            if confidence is not None:
                winner_confidences.append(float(confidence))
        else:
            loss_count += 1
            if confidence is not None:
                loser_confidences.append(float(confidence))

        if ticker:
            ticker_counter[ticker] += 1
        if regime:
            regime_counter[str(regime)] += 1

    # 평균 신뢰도 계산한다
    avg_conf_win = (
        sum(winner_confidences) / len(winner_confidences)
        if winner_confidences
        else 0.0
    )
    avg_conf_loss = (
        sum(loser_confidences) / len(loser_confidences)
        if loser_confidences
        else 0.0
    )

    # 상위 티커 목록을 빈도순으로 정렬한다
    top_tickers = [
        TickerCount(ticker=tk, count=cnt)
        for tk, cnt in ticker_counter.most_common(5)
    ]

    # 가장 빈번한 시장 레짐이다
    most_common_regime = (
        regime_counter.most_common(1)[0][0] if regime_counter else None
    )

    return TradeStatsResponse(
        total_trades=total,
        win_count=win_count,
        loss_count=loss_count,
        total_pnl_amount=round(total_pnl, 2),
        avg_confidence_winners=round(avg_conf_win, 4),
        avg_confidence_losers=round(avg_conf_loss, 4),
        top_tickers=top_tickers,
        most_common_regime=most_common_regime,
    )


@trade_reasoning_router.post(
    "/{trade_id}/feedback",
    response_model=TradeFeedbackResponse,
)
async def submit_feedback(
    trade_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    req: FeedbackRequest = ...,
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
        # trades:reasoning:{date}의 TTL(30일)과 정합하여 90일 보관한다
        await cache.write_json(f"trades:feedback:{trade_id}", feedback, ttl=86400 * 90)
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
    trade_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    req: FeedbackRequest = ...,
    _key: str = Depends(verify_api_key),
) -> TradeFeedbackResponse:
    """PUT 메서드로 매매 피드백을 저장한다. Flutter 호환 별칭이다."""
    return await submit_feedback(trade_id, req, _key=_key)
