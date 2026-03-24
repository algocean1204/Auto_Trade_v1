"""센티넬 루프 -- 2분 주기 이상 감지 루프이다.

매매 윈도우 내에서 룰 기반 + 로컬 AI로 시장 이상을 감지하고,
urgent 신호 발생 시 Sonnet → Opus 3+1 팀 에스컬레이션 경로를 실행한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.analysis.sentinel.anomaly_detector import detect_anomalies
from src.analysis.sentinel.escalation import (
    emergency_opus_judgment,
    evaluate_anomaly,
)
from src.analysis.sentinel.models import (
    AnomalyResult,
    EscalationResult,
    SentinelState,
)
from src.common.logger import get_logger
from src.common.telegram_gateway import escape_html
from src.orchestration.init.dependency_injector import InjectedSystem

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.analysis.models import ComprehensiveReport

logger = get_logger(__name__)

_SENTINEL_INTERVAL_SECONDS: int = 120  # 2분
_SENTINEL_SESSIONS: frozenset[str] = frozenset({
    "pre_market", "power_open", "mid_day", "power_hour", "final_monitoring",
})
_MAX_CONSECUTIVE_ERRORS: int = 10  # 연속 실패 상한 — 초과 시 루프 종료

# 긴급 보고서 전용 캐시 키 — 정기 분석과 분리하여 덮어쓰기 방지
_EMERGENCY_REPORT_KEY: str = "analysis:emergency_report"
_EMERGENCY_REPORT_TTL: int = 300  # 5분
_WATCH_KEY: str = "sentinel:watch"
_WATCH_TTL: int = 3600  # 1시간
_PRIORITY_KEY: str = "sentinel:priority"
_PRIORITY_TTL: int = 7200  # 2시간


async def run_sentinel_loop(
    system: InjectedSystem,
    shutdown_event: asyncio.Event,
) -> SentinelState:
    """2분 주기 센티넬 루프를 실행한다.

    매매 윈도우 내에서만 동작하고, shutdown_event가 set되면 종료한다.
    """
    state = SentinelState()
    consecutive_errors: int = 0
    logger.info("센티넬 루프 시작 (주기=%d초)", _SENTINEL_INTERVAL_SECONDS)

    while not shutdown_event.is_set():
        time_info = system.components.clock.get_time_info()

        # preparation 세션이면 대기 후 재확인한다
        if time_info.session_type == "preparation":
            if await _wait_or_shutdown(shutdown_event, 60):
                break
            continue

        # 매매 윈도우 밖이면 종료한다
        if time_info.session_type not in _SENTINEL_SESSIONS:
            logger.info("센티넬: 매매 윈도우 외 (%s) -- 종료", time_info.session_type)
            break

        prev_errors = len(state.errors)
        await _run_single_scan(system, state)

        # 연속 에러 추적 — 상한 초과 시 루프 종료 (무한 에러 로깅 방지)
        if len(state.errors) > prev_errors:
            consecutive_errors += 1
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                logger.error(
                    "센티넬: 연속 %d회 에러 — 구조적 문제로 판단, 루프 종료",
                    consecutive_errors,
                )
                break
        else:
            consecutive_errors = 0

        if await _wait_or_shutdown(shutdown_event, _SENTINEL_INTERVAL_SECONDS):
            break

    logger.info(
        "센티넬 루프 종료: %d회 스캔, %d 이상 감지, %d 에스컬레이션, %d 긴급",
        state.iterations, state.anomalies_detected,
        state.escalations_triggered, state.emergencies_triggered,
    )
    return state


async def _run_single_scan(
    system: InjectedSystem,
    state: SentinelState,
) -> None:
    """단일 센티넬 스캔을 실행한다."""
    try:
        anomaly, new_vix = await detect_anomalies(system, state)
        state.iterations += 1

        # VIX 이전값 업데이트 (다음 스캔에서 비교용)
        if new_vix is not None:
            state.last_vix = new_vix

        if not anomaly.has_anomaly:
            return

        state.anomalies_detected += 1

        # urgent 신호만 에스컬레이션한다
        if anomaly.highest_level != "urgent":
            # watch 신호는 캐시에 누적 저장하여 다음 정기 분석에 반영한다
            await _accumulate_watch_signals(system, anomaly)
            return

        # Sonnet 에스컬레이션 평가
        state.escalations_triggered += 1
        escalation = await evaluate_anomaly(
            system.components.ai, anomaly, system,
        )

        if escalation.urgency == "ignore":
            logger.info("센티넬: Sonnet이 ignore 판정 — 무시")
            return

        if escalation.urgency == "next_cycle":
            logger.info("센티넬: 다음 정기 분석에 우선 반영")
            await _accumulate_priority_signals(system, anomaly, escalation)
            return

        # emergency → Opus 3+1 팀 긴급 판단
        if escalation.urgency == "emergency":
            state.emergencies_triggered += 1
            logger.warning("센티넬: EMERGENCY — Opus 3+1 팀 긴급 판단 시작")
            report = await emergency_opus_judgment(
                system.components.ai, anomaly, escalation, system,
            )
            # 긴급 보고서를 별도 캐시 키에 저장 (정기 분석 덮어쓰기 방지)
            await system.components.cache.write_json(
                _EMERGENCY_REPORT_KEY,
                report.model_dump(mode="json"),
                ttl=_EMERGENCY_REPORT_TTL,
            )
            # 텔레그램 긴급 알림 (전체 신호 포함)
            await _send_emergency_telegram(system, anomaly, report)

    except Exception as exc:
        msg = f"센티넬 스캔 실패: {exc}"
        logger.error(msg)
        state.errors.append(msg)
        # 에러 리스트 무한 성장 방지: 최대 100건만 유지한다
        if len(state.errors) > 100:
            state.errors = state.errors[-100:]


async def _send_emergency_telegram(
    system: InjectedSystem,
    anomaly: AnomalyResult,
    report: ComprehensiveReport,
) -> None:
    """긴급 판단 결과를 텔레그램으로 전송한다. 모든 감지 신호를 포함한다."""
    try:
        telegram = system.components.telegram

        # 모든 신호를 포함한다 (M2 수정: 첫 번째만 아닌 전체)
        signal_lines = [f"  • {escape_html(str(s.detail))}" for s in anomaly.signals]
        signals_text = "\n".join(signal_lines) if signal_lines else "N/A"

        recs = getattr(report, "recommendations", [])
        recs_text = "\n".join(f"  → {escape_html(str(r))}" for r in recs[:3]) if recs else "N/A"
        confidence = getattr(report, "confidence", 0.0)
        risk_level = escape_html(str(getattr(report, "risk_level", "unknown")))

        await telegram.send_text(
            f"🚨 센티넬 긴급 판단 (Opus 3+1 팀)\n\n"
            f"[감지 신호 {len(anomaly.signals)}건]\n{signals_text}\n\n"
            f"[Opus 팀 판단]\n{recs_text}\n"
            f"신뢰도: {confidence:.0%} | 위험: {risk_level}",
        )
    except Exception as exc:
        logger.warning("긴급 텔레그램 전송 실패: %s", exc)


async def _accumulate_watch_signals(
    system: InjectedSystem,
    anomaly: AnomalyResult,
) -> None:
    """watch 수준 신호를 캐시에 원자적으로 누적 저장한다."""
    new_data = [
        s.model_dump(mode="json")
        for s in anomaly.signals if s.level == "watch"
    ]
    if not new_data:
        return

    cache = system.components.cache
    try:
        await cache.atomic_list_append(
            _WATCH_KEY, new_data, max_size=50, ttl=_WATCH_TTL,
        )
    except Exception as exc:
        logger.warning("watch 신호 누적 저장 실패: %s", exc)


async def _accumulate_priority_signals(
    system: InjectedSystem,
    anomaly: AnomalyResult,
    escalation: EscalationResult,
) -> None:
    """next_cycle로 판정된 신호를 캐시에 원자적으로 누적 저장한다."""
    new_entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "signals": [s.model_dump(mode="json") for s in anomaly.signals],
        "escalation_reasoning": getattr(escalation, "reasoning", ""),
    }

    cache = system.components.cache
    try:
        await cache.atomic_list_append(
            _PRIORITY_KEY, [new_entry], max_size=20, ttl=_PRIORITY_TTL,
        )
    except Exception as exc:
        logger.warning("priority 신호 누적 저장 실패: %s", exc)


async def _wait_or_shutdown(
    shutdown_event: asyncio.Event,
    seconds: int,
) -> bool:
    """대기 중 shutdown 이벤트가 발생하면 True를 반환한다."""
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False
