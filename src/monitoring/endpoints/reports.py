"""F7.28 ReportsEndpoints -- 일별 거래 리포트 조회 API이다.

Redis에 날짜별로 저장된 PnL 이력과 피드백 데이터를 조합하여 반환한다.

Redis 키 구조:
  - pnl:history:{YYYY-MM-DD} : 해당 날짜 PnL + 거래 목록 dict
  - feedback:{YYYY-MM-DD}    : 해당 날짜 피드백 dict (EOD 저장)
  - pnl:history:dates        : 이력이 있는 날짜 목록 list[str]
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

reports_router = APIRouter(prefix="/api/reports", tags=["reports"])

_system: InjectedSystem | None = None


# ── 응답 모델 ──────────────────────────────────────────────────────────────

class DailyReportSummary(BaseModel):
    """일별 리포트 요약 항목 모델이다."""

    date: str
    has_feedback: bool
    trade_count: int
    pnl: float


class DailyReportListResponse(BaseModel):
    """일별 리포트 목록 응답 모델이다."""

    dates: list[DailyReportSummary]
    total: int


class DailyReportResponse(BaseModel):
    """일별 상세 리포트 응답 모델이다.

    Flutter DailyReport.fromJson 형식에 맞춘다:
    summary(Map), by_ticker(Map<ticker, TickerBreakdown>),
    by_hour(Map<hour_str, count>), by_exit_reason(Map<reason, count>),
    risk_metrics(Map), indicator_feedback(Map 또는 null).
    """

    date: str
    summary: dict[str, Any]
    by_ticker: dict[str, Any]
    by_hour: dict[str, int]
    by_exit_reason: dict[str, int]
    risk_metrics: dict[str, Any]
    indicator_feedback: dict[str, Any] | None = None


# ── 의존성 주입 ────────────────────────────────────────────────────────────

def set_reports_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("ReportsEndpoints 의존성 주입 완료")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

def _require_system() -> None:
    """시스템이 초기화되지 않았으면 503 예외를 발생시킨다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")


async def _load_pnl_history(date: str) -> dict[str, Any]:
    """Redis pnl:history:{date} 에서 PnL 이력을 로드한다.

    키가 없으면 빈 dict를 반환한다.
    """
    cache = _system.components.cache  # type: ignore[union-attr]
    raw = await cache.read_json(f"pnl:history:{date}")
    return raw if isinstance(raw, dict) else {}


async def _load_feedback(date: str) -> dict[str, Any] | None:
    """Redis feedback:{date} 에서 피드백을 로드한다.

    키가 없으면 None을 반환한다.
    """
    cache = _system.components.cache  # type: ignore[union-attr]
    raw = await cache.read_json(f"feedback:{date}")
    return raw if isinstance(raw, dict) else None


async def _get_available_dates() -> list[str]:
    """이력이 있는 날짜 목록을 가져온다.

    pnl:history:dates 키를 우선 조회하고, 없으면 빈 목록을 반환한다.
    """
    cache = _system.components.cache  # type: ignore[union-attr]
    raw = await cache.read_json("pnl:history:dates")
    if isinstance(raw, list):
        return [str(d) for d in raw]
    return []


# ── Flutter 응답 변환 헬퍼 ────────────────────────────────────────────────


def _safe_float(value: Any, default: float = 0.0) -> float:
    """값을 float로 안전하게 변환한다."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_summary(
    trades: list[dict[str, Any]], pnl_data: dict[str, Any]
) -> dict[str, Any]:
    """Flutter summary 형식을 구성한다.

    total_trades, total_pnl, win_rate, best_trade, worst_trade를 포함한다.
    """
    total_trades = len(trades)
    pnls = [_safe_float(t.get("pnl", t.get("realized_pnl", 0))) for t in trades]
    total_pnl = _safe_float(
        pnl_data.get("total_pnl", pnl_data.get("pnl", sum(pnls)))
    )
    wins = [p for p in pnls if p > 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0

    # 최고/최저 거래 식별
    best_trade: dict[str, Any] | None = None
    worst_trade: dict[str, Any] | None = None
    if trades:
        best_idx = max(range(len(pnls)), key=lambda i: pnls[i])
        worst_idx = min(range(len(pnls)), key=lambda i: pnls[i])
        best_trade = trades[best_idx]
        worst_trade = trades[worst_idx]

    losses = [p for p in pnls if p <= 0]
    pnl_pcts = [_safe_float(t.get("pnl_pct", 0)) for t in trades]
    avg_pnl_pct = sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0
    max_win_pct = max(pnl_pcts) if pnl_pcts else 0.0
    max_loss_pct = min(pnl_pcts) if pnl_pcts else 0.0
    # 평균 보유 시간 (분) 계산
    hold_minutes: list[float] = []
    for t in trades:
        hm = t.get("hold_minutes", t.get("duration_minutes"))
        if hm is not None:
            hold_minutes.append(_safe_float(hm))
    avg_hold = int(sum(hold_minutes) / len(hold_minutes)) if hold_minutes else 0

    return {
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 2),
        "avg_pnl_pct": round(avg_pnl_pct, 4),
        "max_win_pct": round(max_win_pct, 4),
        "max_loss_pct": round(max_loss_pct, 4),
        "avg_hold_minutes": avg_hold,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
    }


def _aggregate_by_ticker(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """거래를 티커별로 집계한다. {ticker: {trades, total_pnl, avg_pnl_pct}} Map 형식이다.

    Flutter TickerBreakdown.fromJson 이 기대하는 키: trades, total_pnl, avg_pnl_pct.
    """
    ticker_pnls: dict[str, list[float]] = {}
    ticker_pnl_pcts: dict[str, list[float]] = {}
    ticker_counts: dict[str, int] = {}
    for t in trades:
        ticker = t.get("ticker", t.get("symbol", "UNKNOWN"))
        pnl = _safe_float(t.get("pnl", t.get("realized_pnl", 0)))
        pnl_pct = _safe_float(t.get("pnl_pct", 0))
        ticker_pnls.setdefault(ticker, []).append(pnl)
        ticker_pnl_pcts.setdefault(ticker, []).append(pnl_pct)
        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

    result: dict[str, Any] = {}
    for ticker, pnls in ticker_pnls.items():
        pcts = ticker_pnl_pcts.get(ticker, [])
        avg_pct = sum(pcts) / len(pcts) if pcts else 0.0
        result[ticker] = {
            "trades": ticker_counts[ticker],
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl_pct": round(avg_pct, 4),
        }
    return result


def _aggregate_by_hour(trades: list[dict[str, Any]]) -> dict[str, int]:
    """거래를 시간대별로 집계한다. {"0": 3, "14": 5, ...} Map 형식이다.

    Flutter byHour 파싱: Map<String, int> (키=시간 문자열, 값=거래 수).
    """
    hour_counts: dict[int, int] = {}
    for t in trades:
        ts = t.get("entry_time", t.get("timestamp", t.get("time", "")))
        hour = _extract_hour(ts)
        hour_counts[hour] = hour_counts.get(hour, 0) + 1

    return {str(h): c for h, c in sorted(hour_counts.items())}


def _extract_hour(ts: Any) -> int:
    """타임스탬프 문자열에서 시간(hour)을 추출한다. 실패 시 0을 반환한다."""
    if not ts:
        return 0
    ts_str = str(ts)
    # ISO 형식 'YYYY-MM-DDTHH:MM:SS' 또는 'HH:MM' 등에서 시간을 추출한다
    try:
        if "T" in ts_str:
            time_part = ts_str.split("T")[1]
            return int(time_part.split(":")[0])
        if ":" in ts_str:
            return int(ts_str.split(":")[0][-2:])
    except (IndexError, ValueError):
        pass
    return 0


def _aggregate_by_exit_reason(
    trades: list[dict[str, Any]],
) -> dict[str, int]:
    """거래를 청산 사유별로 집계한다. {"stop_loss": 3, "take_profit": 5} Map 형식이다.

    Flutter byExitReason 파싱: Map<String, int> (키=사유, 값=건수).
    """
    reason_counts: dict[str, int] = {}
    for t in trades:
        reason = t.get("exit_reason", t.get("close_reason", "unknown"))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return reason_counts


def _build_risk_metrics(
    trades: list[dict[str, Any]], pnl_data: dict[str, Any]
) -> dict[str, Any]:
    """리스크 지표를 구성한다.

    Flutter RiskMetrics.fromJson 키: max_drawdown_pct, sharpe_estimate, avg_confidence.
    """
    max_drawdown = _safe_float(pnl_data.get("max_drawdown", pnl_data.get("max_drawdown_pct", 0)))

    pnls = [_safe_float(t.get("pnl", t.get("realized_pnl", 0))) for t in trades]
    # 샤프 추정: 평균 수익 / 표준편차 (일일 근사)
    if len(pnls) >= 2:
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = variance ** 0.5
        sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0

    # 평균 신뢰도 추출
    confidences = [_safe_float(t.get("confidence", 0)) for t in trades]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "max_drawdown_pct": round(max_drawdown, 4),
        "sharpe_estimate": round(sharpe, 4),
        "avg_confidence": round(avg_conf, 4),
    }


def _build_indicator_feedback(
    feedback_data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """피드백 데이터에서 지표별 피드백 Map을 구성한다.

    Flutter IndicatorFeedback.fromJson 형식:
    {"macd": {"avg_entry_value":..., "profitable_entries":..., ...}, "recommendation": "..."}
    또는 {"indicators": {지표맵}, "recommendation": "..."}
    피드백이 없으면 None을 반환한다.
    """
    if not feedback_data or not isinstance(feedback_data, dict):
        return None

    indicators = feedback_data.get("indicators", feedback_data.get("indicator_feedback"))

    # dict 형태의 indicators가 있으면 그대로 전달한다
    if isinstance(indicators, dict):
        result: dict[str, Any] = dict(indicators)
        rec = feedback_data.get("recommendation")
        if rec:
            result["recommendation"] = str(rec)
        return result

    # list 형태면 indicator 키로 dict 변환한다
    if isinstance(indicators, list):
        result = {}
        for item in indicators:
            if isinstance(item, dict) and "indicator" in item:
                name = item["indicator"]
                result[name] = {
                    "avg_entry_value": _safe_float(item.get("avg_entry_value", 0)),
                    "profitable_entries": int(_safe_float(item.get("profitable_entries", 0))),
                    "total_entries": int(_safe_float(item.get("total_entries", 0))),
                    "avg_pnl_when_bullish": _safe_float(item.get("avg_pnl_when_bullish", 0)),
                }
        rec = feedback_data.get("recommendation")
        if rec:
            result["recommendation"] = str(rec)
        return result if result else None

    # 최상위에 지표 관련 키가 흩어져 있는 경우 Map으로 수집한다
    result = {}
    for key, value in feedback_data.items():
        if key in ("date", "created_at", "updated_at", "recommendation"):
            continue
        if isinstance(value, dict):
            result[key] = {
                "avg_entry_value": _safe_float(value.get("avg_entry_value", value.get("accuracy", 0))),
                "profitable_entries": int(_safe_float(value.get("profitable_entries", 0))),
                "total_entries": int(_safe_float(value.get("total_entries", 0))),
                "avg_pnl_when_bullish": _safe_float(value.get("avg_pnl_when_bullish", 0)),
            }
    rec = feedback_data.get("recommendation")
    if rec:
        result["recommendation"] = str(rec)
    return result if result else None


# ── 엔드포인트 ────────────────────────────────────────────────────────────

@reports_router.get("/daily/list", response_model=DailyReportListResponse)
async def get_daily_report_list(limit: int = 30) -> DailyReportListResponse:
    """일별 리포트 목록을 반환한다.

    각 날짜별로 거래 수, PnL, 피드백 존재 여부를 포함한다.
    Redis pnl:history:* 키 기반으로 구성한다.
    """
    _require_system()
    try:
        dates = await _get_available_dates()
        # 최신 날짜 순으로 정렬
        dates_sorted = sorted(dates, reverse=True)[:limit]

        summaries: list[DailyReportSummary] = []
        for date in dates_sorted:
            pnl_data = await _load_pnl_history(date)
            feedback_data = await _load_feedback(date)

            # 거래 목록 추출 (저장 형식에 따라 trades 또는 trade_logs 키 사용)
            trades: list = pnl_data.get("trades", pnl_data.get("trade_logs", []))
            trade_count = len(trades) if isinstance(trades, list) else 0

            # PnL 금액 추출 (float 보장)
            pnl_val = pnl_data.get("total_pnl", pnl_data.get("pnl", 0.0))
            try:
                pnl_float = float(pnl_val)
            except (TypeError, ValueError):
                pnl_float = 0.0

            summaries.append(
                DailyReportSummary(
                    date=date,
                    has_feedback=feedback_data is not None,
                    trade_count=trade_count,
                    pnl=pnl_float,
                )
            )

        return DailyReportListResponse(dates=summaries, total=len(summaries))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 리포트 목록 조회 실패")
        raise HTTPException(status_code=500, detail="리포트 목록 조회 실패") from None


@reports_router.get("/daily", response_model=DailyReportResponse)
async def get_daily_report(date: str) -> DailyReportResponse:
    """특정 날짜의 상세 리포트를 반환한다.

    date 파라미터 형식: YYYY-MM-DD
    Redis pnl:history:{date} 와 feedback:{date} 키를 조합하여 반환한다.
    Flutter DailyReport.fromJson 형식에 맞춰 응답을 구성한다.
    해당 날짜 데이터가 없으면 404를 반환한다.
    """
    _require_system()
    try:
        pnl_data = await _load_pnl_history(date)
        if not pnl_data:
            raise HTTPException(
                status_code=404,
                detail=f"해당 날짜의 리포트가 없다: {date}",
            )

        feedback_data = await _load_feedback(date)

        # 거래 목록 정규화
        trades_raw = pnl_data.get("trades", pnl_data.get("trade_logs", []))
        trades: list[dict[str, Any]] = (
            trades_raw if isinstance(trades_raw, list) else []
        )

        # ── summary 구성 ──
        summary = _build_summary(trades, pnl_data)

        # ── by_ticker 집계 ──
        by_ticker = _aggregate_by_ticker(trades)

        # ── by_hour 집계 ──
        by_hour = _aggregate_by_hour(trades)

        # ── by_exit_reason 집계 ──
        by_exit_reason = _aggregate_by_exit_reason(trades)

        # ── risk_metrics 구성 ──
        risk_metrics = _build_risk_metrics(trades, pnl_data)

        # ── indicator_feedback 구성 (피드백 데이터 기반) ──
        indicator_feedback = _build_indicator_feedback(feedback_data)

        return DailyReportResponse(
            date=date,
            summary=summary,
            by_ticker=by_ticker,
            by_hour=by_hour,
            by_exit_reason=by_exit_reason,
            risk_metrics=risk_metrics,
            indicator_feedback=indicator_feedback,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 상세 리포트 조회 실패: %s", date)
        raise HTTPException(status_code=500, detail="리포트 조회 실패") from None
