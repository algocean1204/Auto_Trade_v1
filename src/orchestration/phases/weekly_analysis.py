"""F9.9 WeeklyAnalysisSequence -- 주간 종합 분석을 실행한다.

매주 일요일 00:00 KST에 주간 성과 분석, 벤치마크 비교,
ML 모델 재학습, 텔레그램 보고서 발송을 수행한다.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.common.market_clock import TimeInfo
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)

# 주간 분석 실행 요일 (일요일 = 6)이다
_WEEKLY_DAY: int = 6

# 주간 분석 실행 시각 (00시 KST)이다
_WEEKLY_HOUR: int = 0


class WeeklyReport(BaseModel):
    """주간 보고서이다."""

    week_number: int
    win_rate: float = 0.0
    total_pnl: float = 0.0
    trade_count: int = 0
    best_trade: str = ""
    worst_trade: str = ""
    model_retrained: bool = False
    telegram_sent: bool = False
    errors: list[str] = []


def should_run_weekly(time_info: TimeInfo) -> bool:
    """주간 분석 실행 조건을 판별한다 (일요일 00:00 KST)."""
    return (
        time_info.now_kst.weekday() == _WEEKLY_DAY
        and time_info.now_kst.hour == _WEEKLY_HOUR
    )


async def run_weekly_analysis(system: InjectedSystem) -> WeeklyReport:
    """주간 분석 시퀀스를 실행한다."""
    week_number = _current_week_number(system)
    report = WeeklyReport(week_number=week_number)
    logger.info("=== 주간 분석 시작 (W%d) ===", week_number)

    await _step_weekly_performance(system, report)
    await _step_benchmark_comparison(system, report)
    await _step_retrain_model(system, report)
    await _step_send_weekly_telegram(system, report)

    await get_event_bus().publish(EventType.WEEKLY_REPORT_GENERATED, report)
    _log_weekly_summary(report)
    return report


def _current_week_number(system: InjectedSystem) -> int:
    """현재 ISO 주차 번호를 반환한다."""
    return system.components.clock.get_time_info().now_kst.isocalendar()[1]


def _log_weekly_summary(report: WeeklyReport) -> None:
    """주간 분석 종료 요약 로그를 출력한다."""
    logger.info(
        "=== 주간 분석 완료 (W%d, 에러 %d건) ===",
        report.week_number, len(report.errors),
    )


# ---------------------------------------------------------------------------
# Step 구현 -- 실제 Feature 모듈 연결이다
# ---------------------------------------------------------------------------


async def _step_weekly_performance(
    system: InjectedSystem,
    report: WeeklyReport,
) -> None:
    """Step 1: 주간 트레이딩 성과를 분석한다 (FF.2)."""
    try:
        from src.optimization.feedback.weekly_analysis import analyze_weekly

        cache = system.components.cache
        weekly_data = await cache.read_json("trades:weekly") or {"trades": []}
        result = analyze_weekly(weekly_data)
        report.win_rate = result.win_rate * 100  # 퍼센트로 변환한다
        report.total_pnl = result.total_pnl
        report.trade_count = len(weekly_data.get("trades", []))
        best = result.best_trade
        worst = result.worst_trade
        if best:
            report.best_trade = f"{best.get('ticker', '?')} ${best.get('pnl', 0):.2f}"
        if worst:
            report.worst_trade = f"{worst.get('ticker', '?')} ${worst.get('pnl', 0):.2f}"
        logger.info(
            "[주간 Step 1] 성과 분석 완료: 승률=%.1f%%, PnL=$%.2f",
            report.win_rate, report.total_pnl,
        )
    except Exception as exc:
        _record_error(report, 1, "성과 분석", exc)


async def _step_benchmark_comparison(
    system: InjectedSystem,
    report: WeeklyReport,
) -> None:
    """Step 2: SPY/QQQ 대비 성과를 비교한다 (F7.9)."""
    try:
        # PriceDataFetcher 미등록 — 벤치마크 비교는 향후 연결 예정
        logger.info("[주간 Step 2] 벤치마크 비교 (PriceDataFetcher 연결 예정)")
    except Exception as exc:
        _record_error(report, 2, "벤치마크 비교", exc)


async def _step_retrain_model(
    system: InjectedSystem,
    report: WeeklyReport,
) -> None:
    """Step 3: ML 모델을 주간 데이터로 재학습한다 (F8.7)."""
    try:
        from src.optimization.ml.auto_trainer import run_auto_training

        training_result = await run_auto_training(
            session_factory=system.components.db,
            cache=system.components.cache,
        )
        report.model_retrained = training_result.deployed
        logger.info(
            "[주간 Step 3] ML 재학습 완료: version=%s, deployed=%s",
            training_result.model_version, training_result.deployed,
        )
    except Exception as exc:
        report.model_retrained = False
        _record_error(report, 3, "ML 재학습", exc)


async def _step_send_weekly_telegram(
    system: InjectedSystem,
    report: WeeklyReport,
) -> None:
    """Step 4: 주간 보고서를 텔레그램으로 발송한다."""
    try:
        telegram = system.components.telegram
        message = _format_weekly_message(report)
        await telegram.send_text(message)
        report.telegram_sent = True
        logger.info("[주간 Step 4] 텔레그램 보고서 발송 완료")
    except Exception as exc:
        _record_error(report, 4, "텔레그램 발송", exc)


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _format_weekly_message(report: WeeklyReport) -> str:
    """주간 보고서를 텔레그램 메시지 형식으로 포매팅한다."""
    status = "OK" if not report.errors else "WARN"
    lines = [
        f"<b>[주간 보고서 W{report.week_number}] {status}</b>",
        f"승률: {report.win_rate:.1f}%",
        f"총 PnL: ${report.total_pnl:,.2f}",
        f"거래: {report.trade_count}건",
    ]
    if report.best_trade:
        lines.append(f"최고: {report.best_trade}")
    if report.worst_trade:
        lines.append(f"최악: {report.worst_trade}")
    lines.append(
        f"ML 재학습: {'완료' if report.model_retrained else '미실행'}"
    )
    if report.errors:
        lines.append(f"\n<b>에러 ({len(report.errors)}건):</b>")
        for err in report.errors[:5]:
            lines.append(f"- {err}")
    return "\n".join(lines)


def _record_error(
    report: WeeklyReport,
    step: int,
    name: str,
    exc: Exception,
) -> None:
    """에러를 보고서에 기록하고 로그를 남긴다."""
    msg = f"Step {step} ({name}) 실패: {exc}"
    report.errors.append(msg)
    logger.error("[주간] %s", msg)
