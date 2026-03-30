"""Tier3 AI 분석 -- Opus로 에러를 진단하고 텔레그램으로 보고한다.

코드 수정은 하지 않으며, 근본 원인 분석과 권장 대응책을 제시한다.
AiClient 미사용 시 원시 에러 데이터를 텔레그램으로 전송하여 그레이스풀 디그레이드한다.
"""
from __future__ import annotations

import logging

from src.common.logger import get_logger
from src.healing.budget_tracker import BudgetTracker
from src.healing.error_classifier import ErrorEvent, RepairResult, RepairTier

logger: logging.Logger = get_logger(__name__)

_SYSTEM_PROMPT: str = (
    "너는 자동매매 시스템의 에러 진단 전문가이다. "
    "주어진 에러 이벤트를 분석하여 근본 원인, 심각도, 권장 수정 방안, 임시 대응책을 제시한다."
)


def _build_analysis_prompt(events: list[ErrorEvent]) -> str:
    """에러 이벤트 목록을 Opus 분석용 프롬프트로 구성한다."""
    lines: list[str] = ["[자동매매 시스템 에러 분석 요청]", f"에러 건수: {len(events)}", ""]
    for i, ev in enumerate(events, 1):
        lines.append(f"--- 에러 #{i} ---")
        lines.append(f"유형: {ev.error_type}")
        lines.append(f"메시지: {ev.message}")
        lines.append(f"모듈: {ev.module}")
        lines.append(f"시각: {ev.timestamp.isoformat()}")
        if ev.detail:
            lines.append(f"상세: {ev.detail}")
        lines.append("")
    lines.append("다음 항목을 분석하라:")
    lines.append("1. 근본 원인 분석")
    lines.append("2. 심각도 평가 (Critical/High/Medium/Low)")
    lines.append("3. 권장 수정 방안")
    lines.append("4. 임시 대응책")
    return "\n".join(lines)


async def _send_telegram_report(system: object, analysis: str, event_count: int) -> None:
    """분석 결과를 텔레그램으로 전송한다."""
    try:
        components = getattr(system, "components", None)
        telegram = getattr(components, "telegram", None) if components else None
        if telegram is None:
            logger.warning("텔레그램 접근 불가 — 보고서 전송 건너뜀")
            return
        # HTML 형식 메시지 구성 — escape 처리로 파싱 오류를 방지한다
        from src.common.telegram_gateway import escape_html
        safe_analysis = escape_html(analysis)
        msg = (
            f"<b>[Self-Healing] 에러 진단 보고</b>\n"
            f"분석 대상: {event_count}건\n\n"
            f"<pre>{safe_analysis[:3500]}</pre>"
        )
        await telegram.send_text(msg)
        logger.info("텔레그램 진단 보고 전송 완료")
    except Exception as exc:
        # 텔레그램 전송 실패는 치명적이지 않으므로 로그만 남긴다
        logger.error("텔레그램 보고 전송 실패: %s", exc)


async def attempt_tier3(
    system: object,
    events: list[ErrorEvent],
    budget: BudgetTracker,
) -> RepairResult:
    """Tier3 AI 분석을 수행한다. 예산 초과 시 원시 데이터만 텔레그램으로 전송한다."""
    if not events:
        return RepairResult(success=True, tier=RepairTier.TIER3, action="AI 분석", detail="분석 대상 없음")

    prompt = _build_analysis_prompt(events)

    # 예산 부족 시 AI 없이 원시 에러 덤프만 텔레그램으로 전송한다
    if not budget.can_call("opus"):
        logger.warning("Opus 예산 초과 — 원시 에러 데이터로 텔레그램 보고")
        await _send_telegram_report(system, prompt, len(events))
        return RepairResult(
            success=True, tier=RepairTier.TIER3, action="AI 분석 (예산 초과 → 원시 데이터)",
            detail=f"{len(events)}건 원시 보고",
        )

    # AiClient를 통한 Opus 진단
    try:
        from src.common.ai_gateway import get_ai_client
        ai_client = get_ai_client()
        response = await ai_client.send_text(
            prompt=prompt, system=_SYSTEM_PROMPT, model="opus", max_tokens=2048,
        )
        budget.record_call("opus")
        analysis = response.content
    except Exception as exc:
        # AI 호출 실패 시 원시 데이터를 텔레그램으로 전송하여 디그레이드한다
        logger.error("Opus 호출 실패 — 원시 데이터로 폴백: %s", exc)
        await _send_telegram_report(system, prompt, len(events))
        return RepairResult(
            success=False, tier=RepairTier.TIER3, action="AI 분석",
            detail=f"Opus 호출 실패: {exc}",
        )

    # 분석 결과를 텔레그램으로 전송한다
    await _send_telegram_report(system, analysis, len(events))
    return RepairResult(
        success=True, tier=RepairTier.TIER3, action="AI 분석",
        detail=f"{len(events)}건 분석 완료",
    )
