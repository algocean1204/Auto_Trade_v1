"""FF 피드백 -- 일일 성과 분석 + 피드백이다."""

from __future__ import annotations

import math

from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger
from src.optimization.feedback.models import DailyFeedbackResult

logger = get_logger(__name__)

# 분석 임계값이다
_WIN_RATE_LOW: float = 0.4
_WIN_RATE_HIGH: float = 0.7
_PNL_RATIO_LOW: float = 1.0
_MAX_DRAWDOWN_WARN: float = -0.03


def _safe_float(val: float | str | None, default: float = 0.0) -> float:
    """안전하게 float 변환한다. NaN/inf이면 기본값을 반환한다."""
    if val is None:
        return default
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def _compute_summary(trades: list[dict]) -> dict:
    """거래 통계를 계산한다."""
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0}

    pnls = [_safe_float(t.get("pnl")) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)

    return {
        "total": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades),
        "total_pnl": sum(pnls),
        "avg_pnl": sum(pnls) / len(pnls),
        "max_gain": max(pnls) if pnls else 0.0,
        "max_loss": min(pnls) if pnls else 0.0,
    }


def _extract_lessons(trades: list[dict], summary: dict) -> list[str]:
    """거래 패턴에서 교훈을 추출한다."""
    lessons: list[str] = []
    win_rate = summary.get("win_rate", 0.0)

    if win_rate < _WIN_RATE_LOW:
        lessons.append(f"승률 {win_rate:.1%}로 낮음 -- 진입 조건 강화 필요")

    if win_rate > _WIN_RATE_HIGH:
        lessons.append(f"승률 {win_rate:.1%}로 높음 -- 포지션 확대 검토 가능")

    # 손익비 분석이다
    gains = [_safe_float(t.get("pnl")) for t in trades if _safe_float(t.get("pnl")) > 0]
    losses = [abs(_safe_float(t.get("pnl"))) for t in trades if _safe_float(t.get("pnl")) < 0]
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 1.0
    pnl_ratio = avg_gain / avg_loss if avg_loss > 0 else 0.0

    if pnl_ratio < _PNL_RATIO_LOW:
        lessons.append(f"손익비 {pnl_ratio:.2f} -- 익절 목표 상향 또는 손절 축소 필요")

    # 최대 손실 분석이다
    max_loss = summary.get("max_loss", 0.0)
    if max_loss < _MAX_DRAWDOWN_WARN:
        lessons.append(f"최대 손실 {max_loss:.2%} -- 리스크 관리 점검 필요")

    return lessons


def _suggest_improvements(
    trades: list[dict], summary: dict,
) -> list[str]:
    """개선 제안을 생성한다."""
    improvements: list[str] = []

    # 연속 손실 패턴 감지이다
    consecutive_losses = _count_max_consecutive_losses(trades)
    if consecutive_losses >= 3:
        improvements.append(
            f"연속 {consecutive_losses}회 손실 -- 틸트 방지 쿨다운 강화 권장"
        )

    # 거래 빈도 분석이다
    total = summary.get("total", 0)
    if total > 20:
        improvements.append(f"일 {total}회 거래 -- 과매매 가능성, 진입 필터 강화 검토")
    elif total < 3 and total > 0:
        improvements.append(f"일 {total}회 거래 -- 기회 탐색 범위 확대 검토")

    # 보유 시간 분석이다
    hold_times = [_safe_float(t.get("hold_minutes")) for t in trades if _safe_float(t.get("hold_minutes")) > 0]
    if hold_times:
        avg_hold = sum(hold_times) / len(hold_times)
        if avg_hold < 2:
            improvements.append(f"평균 보유 {avg_hold:.1f}분 -- 너무 빠른 청산, 트레일링 완화 검토")

    return improvements


def _count_max_consecutive_losses(trades: list[dict]) -> int:
    """최대 연속 손실 횟수를 계산한다."""
    max_streak = 0
    current = 0
    for t in trades:
        if _safe_float(t.get("pnl")) < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


async def analyze_daily(
    daily_trades: list[dict],
    session_factory: SessionFactory | None = None,
) -> DailyFeedbackResult:
    """일일 거래를 분석하여 피드백 결과를 생성한다.

    승률, 손익비, 연속 손실, 보유 시간 등을 분석하여
    교훈과 개선 제안을 도출한다.
    """
    logger.info("일일 피드백 분석 시작: %d trades", len(daily_trades))

    summary = _compute_summary(daily_trades)
    lessons = _extract_lessons(daily_trades, summary)
    improvements = _suggest_improvements(daily_trades, summary)

    logger.info(
        "분석 완료: 승률=%.1f%%, PnL=$%.2f, 교훈=%d, 개선=%d",
        summary.get("win_rate", 0) * 100,
        summary.get("total_pnl", 0),
        len(lessons),
        len(improvements),
    )

    return DailyFeedbackResult(
        summary=summary,
        lessons=lessons,
        improvements=improvements,
    )
