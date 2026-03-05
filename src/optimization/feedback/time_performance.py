"""FF 피드백 -- 시간대별 성과 분석이다."""

from __future__ import annotations

from src.common.logger import get_logger
from src.optimization.feedback.models import TimePerformanceResult

logger = get_logger(__name__)

# 분석 대상 시간 범위 (ET 기준)이다
_MARKET_OPEN_HOUR: int = 9
_MARKET_CLOSE_HOUR: int = 16

# best/worst 상위 N개이다
_TOP_N: int = 3


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전하게 float 변환한다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _extract_hour(trade: dict) -> int | None:
    """거래에서 시간(hour)을 추출한다."""
    # hour 필드가 직접 있는 경우이다
    hour = trade.get("hour")
    if hour is not None:
        try:
            return int(hour)
        except (ValueError, TypeError):
            pass

    # created_at에서 추출한다
    created = trade.get("created_at")
    if created is not None and hasattr(created, "hour"):
        return created.hour

    # 문자열 파싱이다
    ts_str = str(trade.get("created_at", ""))
    if len(ts_str) >= 13 and "T" in ts_str:
        try:
            return int(ts_str.split("T")[1][:2])
        except (ValueError, IndexError):
            pass

    return None


def _aggregate_by_hour(trades: list[dict]) -> dict[int, float]:
    """시간대별 총 PnL을 집계한다."""
    hourly: dict[int, float] = {}

    for trade in trades:
        hour = _extract_hour(trade)
        if hour is None:
            continue
        pnl = _safe_float(trade.get("pnl"))
        hourly[hour] = hourly.get(hour, 0.0) + pnl

    return hourly


def _find_best_hours(
    hourly_pnl: dict[int, float],
) -> list[int]:
    """PnL이 가장 높은 시간대를 반환한다."""
    if not hourly_pnl:
        return []
    sorted_hours = sorted(
        hourly_pnl.items(), key=lambda x: x[1], reverse=True,
    )
    return [h for h, _ in sorted_hours[:_TOP_N] if hourly_pnl[h] > 0]


def _find_worst_hours(
    hourly_pnl: dict[int, float],
) -> list[int]:
    """PnL이 가장 낮은 시간대를 반환한다."""
    if not hourly_pnl:
        return []
    sorted_hours = sorted(
        hourly_pnl.items(), key=lambda x: x[1],
    )
    return [h for h, _ in sorted_hours[:_TOP_N] if hourly_pnl[h] < 0]


def analyze_time_performance(
    trades: list[dict],
) -> TimePerformanceResult:
    """시간대별 거래 성과를 분석한다.

    각 시간(hour)별 총 PnL을 집계하고,
    가장 수익성 높은/낮은 시간대를 식별한다.
    """
    logger.info("시간대별 성과 분석 시작: %d trades", len(trades))

    hourly_pnl = _aggregate_by_hour(trades)
    best = _find_best_hours(hourly_pnl)
    worst = _find_worst_hours(hourly_pnl)

    # 로그 출력이다
    for hour in sorted(hourly_pnl.keys()):
        pnl = hourly_pnl[hour]
        marker = "+" if pnl > 0 else ""
        logger.info("  %02d시: %s$%.2f", hour, marker, pnl)

    logger.info(
        "분석 완료: best=%s, worst=%s", best, worst,
    )

    return TimePerformanceResult(
        hourly_pnl=hourly_pnl,
        best_hours=best,
        worst_hours=worst,
    )
