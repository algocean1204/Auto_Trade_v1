"""에러 자체수리 매니저 -- Tier별로 수리를 디스패치하고 서킷 브레이커를 관리한다.

동일 에러 유형이 반복 실패하면 서킷 브레이커를 발동하여 불필요한 재시도를 차단한다.
Haiku 사전 스크리닝으로 Tier 2/3를 분별하여 Opus 호출을 절약한다.
수리 학습 캐시로 반복 에러를 즉시 처리한다.
"""
from __future__ import annotations

import logging

from src.common.logger import get_logger
from src.healing.budget_tracker import BudgetTracker
from src.healing.error_classifier import (
    ErrorEvent,
    RepairResult,
    RepairTier,
    classify_tier,
)
from src.healing.repair_cache import RepairCache
from src.healing.tier1_5_prompt import attempt_tier1_5
from src.healing.tier1_ops import attempt_tier1
from src.healing.tier2_config import attempt_tier2
from src.healing.tier3_analysis import attempt_tier3
from src.healing.tier3_code_repair import attempt_code_repair
from src.orchestration.init.dependency_injector import InjectedSystem

logger: logging.Logger = get_logger(__name__)

# Haiku 스크리닝 프롬프트 — 에러를 빠르게 분류한다
_HAIKU_SCREEN_SYSTEM: str = (
    "너는 자동매매 시스템 에러 분류기이다. "
    "에러를 보고 아래 중 하나로 분류하라: "
    "CONFIG(설정 조정으로 해결 가능), CODE(코드 수정 필요), PROMPT(프롬프트 조정으로 해결 가능). "
    "분류만 출력하라. 설명 없음."
)


class SelfRepairManager:
    """에러 자체수리 매니저이다. Tier별 수리를 디스패치하고 반복 실패를 차단한다."""

    _MAX_ATTEMPTS_PER_TYPE: int = 3

    def __init__(self, system: InjectedSystem) -> None:
        self._system = system
        self._budget = BudgetTracker()
        self._cache = RepairCache()
        self._attempt_counts: dict[str, int] = {}
        self._repair_history: list[RepairResult] = []

    async def attempt_repair(self, event: ErrorEvent) -> RepairResult:
        """에러 이벤트를 분류하고 적절한 Tier 수리를 시도한다."""
        # 서킷 브레이커 확인
        count = self._attempt_counts.get(event.error_type, 0)
        if count >= self._MAX_ATTEMPTS_PER_TYPE:
            logger.error("서킷 브레이커 발동: %s (%d회 반복)", event.error_type, count)
            return RepairResult(
                success=False, tier=event.tier,
                action="서킷 브레이커 발동",
                detail=f"{event.error_type} {count}회 반복 실패",
            )

        # 캐시 조회 — 이전에 성공한 수리가 있으면 빠르게 재시도
        cached = self._cache.lookup(event.error_type)
        if cached and cached.get("success_count", 0) >= 1:
            result = await self._try_cached_repair(event, cached)
            if result.success:
                self._repair_history.append(result)
                return result
            # 캐시 수리 실패 시 정상 흐름으로 계속 진행한다
            self._cache.record_failure(event.error_type)

        # Tier 분류
        tier = classify_tier(event)
        event.tier = tier

        # Tier별 디스패치
        if tier == RepairTier.TIER1:
            result = await attempt_tier1(self._system, event)
        elif tier == RepairTier.TIER1_5:
            result = await attempt_tier1_5(event)
        elif tier == RepairTier.TIER2:
            result = await attempt_tier2(event)
        else:
            # Tier3: Haiku 스크리닝 → 분석 → 코드 수리
            result = await self._handle_tier3(event)

        self._attempt_counts[event.error_type] = count + (0 if result.success else 1)
        self._repair_history.append(result)
        return result

    async def _haiku_screen(self, event: ErrorEvent) -> str:
        """Haiku로 에러를 사전 스크리닝한다. CONFIG/CODE/PROMPT를 반환한다."""
        if not self._budget.can_call("haiku"):
            return "CODE"  # 예산 부족 시 기본값
        try:
            from src.common.ai_gateway import get_ai_client
            ai = get_ai_client()
            prompt = f"에러: {event.error_type}\n메시지: {event.message}\n모듈: {event.module}"
            resp = await ai.send_text(
                prompt=prompt, system=_HAIKU_SCREEN_SYSTEM,
                model="haiku", max_tokens=20,
            )
            self._budget.record_call("haiku")
            verdict = resp.content.strip().upper()
            if "CONFIG" in verdict:
                return "CONFIG"
            if "PROMPT" in verdict:
                return "PROMPT"
            return "CODE"
        except Exception as exc:
            logger.warning("Haiku 스크리닝 실패 (CODE로 진행): %s", exc)
            return "CODE"

    async def _handle_tier3(self, event: ErrorEvent) -> RepairResult:
        """Tier 3 처리 — Haiku 스크리닝 후 분석 + 코드 수리를 시도한다."""
        # Haiku 사전 스크리닝으로 다운그레이드 가능성 확인
        screen = await self._haiku_screen(event)

        if screen == "CONFIG":
            logger.info("Haiku 스크리닝: CONFIG → Tier 2로 다운그레이드")
            return await attempt_tier2(event)

        if screen == "PROMPT":
            logger.info("Haiku 스크리닝: PROMPT → Tier 1.5로 다운그레이드")
            return await attempt_tier1_5(event)

        # CODE → AI 분석 + 코드 수리
        result = await attempt_tier3(self._system, [event], self._budget)
        if result.success:
            repair = await attempt_code_repair(
                self._system, [event], self._budget, cache=self._cache,
            )
            if repair.success:
                self._cache.record_success(
                    event.error_type,
                    repair.detail or "",
                    repair.action,
                )
                return repair
        return result

    async def _try_cached_repair(
        self, event: ErrorEvent, cached: dict,
    ) -> RepairResult:
        """캐시된 수리를 재적용한다. 검증됨이면 Opus 검증을 건너뛴다."""
        file_path = cached.get("file_path", "")
        is_verified = self._cache.is_verified(event.error_type)

        # Sticky Fix 확인
        if file_path and self._cache.is_sticky(file_path):
            logger.info("Sticky Fix 활성: %s — 수리 건너뜀", file_path)
            return RepairResult(
                success=False, tier=RepairTier.TIER3,
                action="캐시 수리 (Sticky)", detail=f"cooldown 중: {file_path}",
            )

        logger.info(
            "캐시 수리 시도: %s (verified=%s)", event.error_type, is_verified,
        )
        # 검증됨 수리는 Opus 검증 없이 바로 코드 수리를 시도한다
        # 미검증 수리는 정상 파이프라인(Opus→Sonnet→Opus)을 따른다
        repair = await attempt_code_repair(
            self._system, [event], self._budget, cache=self._cache,
        )
        if repair.success:
            self._cache.record_success(event.error_type, file_path, repair.action)
            self._cache.set_sticky(file_path)
        return repair

    def get_status(self) -> dict[str, object]:
        """수리 이력, 서킷 브레이커, 캐시 상태를 반환한다."""
        return {
            "total_repairs": len(self._repair_history),
            "success_count": sum(1 for r in self._repair_history if r.success),
            "circuit_breakers": {
                k: v for k, v in self._attempt_counts.items()
                if v >= self._MAX_ATTEMPTS_PER_TYPE
            },
            "budget": self._budget.get_summary(),
            "cache": self._cache.get_status(),
        }

    def reset_session(self) -> None:
        """새 세션을 위해 카운터를 초기화한다. 학습 캐시는 유지한다."""
        self._attempt_counts.clear()
        self._repair_history.clear()
        self._budget.reset()
        self._cache.reset()  # sticky/rollback만 리셋, 학습 캐시는 유지
        logger.info("SelfRepairManager 세션 초기화 완료")
