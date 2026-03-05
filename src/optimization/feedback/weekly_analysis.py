"""FF 피드백 -- 주간 성과 분석이다."""

from __future__ import annotations

from src.common.logger import get_logger
from src.optimization.feedback.models import WeeklyReport

logger = get_logger(__name__)


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전하게 float 변환한다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _calculate_win_rate(trades: list[dict]) -> float:
    """주간 승률을 계산한다."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if _safe_float(t.get("pnl")) > 0)
    return wins / len(trades)


def _find_best_trade(trades: list[dict]) -> dict:
    """최고 수익 거래를 찾는다."""
    if not trades:
        return {}
    return max(trades, key=lambda t: _safe_float(t.get("pnl")))


def _find_worst_trade(trades: list[dict]) -> dict:
    """최대 손실 거래를 찾는다."""
    if not trades:
        return {}
    return min(trades, key=lambda t: _safe_float(t.get("pnl")))


def _detect_patterns(trades: list[dict]) -> list[str]:
    """주간 거래 패턴을 감지한다."""
    patterns: list[str] = []
    if not trades:
        return patterns

    # 요일별 성과 패턴이다
    day_pnl: dict[str, list[float]] = {}
    for t in trades:
        day = str(t.get("day_of_week", "unknown"))
        day_pnl.setdefault(day, []).append(_safe_float(t.get("pnl")))

    for day, pnls in day_pnl.items():
        avg = sum(pnls) / len(pnls) if pnls else 0
        if avg > 0:
            patterns.append(f"{day}요일 평균 수익 ${avg:.2f}")
        elif avg < -10:
            patterns.append(f"{day}요일 평균 손실 ${avg:.2f} -- 주의 필요")

    # 시간대별 집중도이다
    hour_counts: dict[int, int] = {}
    for t in trades:
        hour = int(_safe_float(t.get("hour", 0)))
        hour_counts[hour] = hour_counts.get(hour, 0) + 1

    if hour_counts:
        peak_hour = max(hour_counts, key=hour_counts.get)  # type: ignore[arg-type]
        patterns.append(f"거래 집중 시간: {peak_hour}시 ({hour_counts[peak_hour]}건)")

    # 연속 손실 패턴이다
    max_streak = _max_consecutive_losses(trades)
    if max_streak >= 3:
        patterns.append(f"최대 연속 손실 {max_streak}회 -- 틸트 위험")

    return patterns


def _max_consecutive_losses(trades: list[dict]) -> int:
    """최대 연속 손실 횟수이다."""
    max_streak = 0
    current = 0
    for t in trades:
        if _safe_float(t.get("pnl")) < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def analyze_weekly(weekly_data: dict) -> WeeklyReport:
    """주간 거래 데이터를 종합 분석한다.

    승률, 총 PnL, 최고/최악 거래, 요일/시간 패턴을
    분석하여 WeeklyReport로 반환한다.
    """
    trades: list[dict] = weekly_data.get("trades", [])

    logger.info("주간 분석 시작: %d trades", len(trades))

    win_rate = _calculate_win_rate(trades)
    total_pnl = sum(_safe_float(t.get("pnl")) for t in trades)
    best = _find_best_trade(trades)
    worst = _find_worst_trade(trades)
    patterns = _detect_patterns(trades)

    logger.info(
        "주간 분석 완료: 승률=%.1f%%, PnL=$%.2f, 패턴=%d",
        win_rate * 100, total_pnl, len(patterns),
    )

    return WeeklyReport(
        win_rate=win_rate,
        total_pnl=total_pnl,
        best_trade=best,
        worst_trade=worst,
        patterns=patterns,
    )
