"""에러 모니터링봇 -- 매매 세션 중 에러를 수집하고 주기적으로 자동 수리를 트리거한다.

5분 주기로 수집된 에러를 검토하고, 모듈+시간 기반 그룹화로 연관 에러를 묶어 처리한다.
그룹 단위로 1회 수리를 호출하여 Opus 호출을 절약한다.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict

from src.common.logger import get_logger
from src.healing.error_classifier import ErrorEvent, create_error_event
from src.healing.self_repair import SelfRepairManager
from src.orchestration.init.dependency_injector import InjectedSystem

logger: logging.Logger = get_logger(__name__)

# 같은 모듈에서 이 시간(초) 내 발생한 에러를 그룹으로 묶는다
_GROUP_WINDOW_SECONDS: int = 300


class ErrorMonitor:
    """에러 모니터링봇이다. 매매 중 발생하는 에러를 수집하고 자동 수리를 트리거한다."""

    _REVIEW_INTERVAL: int = 300

    def __init__(self, system: InjectedSystem) -> None:
        self._system = system
        self._repair_manager = SelfRepairManager(system)
        self._pending_errors: list[ErrorEvent] = []
        self._total_errors: int = 0
        self._total_repairs: int = 0
        self._running: bool = False

    def record_error(self, exc: Exception, module: str) -> None:
        """에러를 수집 큐에 추가한다."""
        event = create_error_event(exc, module)
        self._pending_errors.append(event)
        self._total_errors += 1
        logger.warning("에러 수집: [%s] %s (%s)", event.tier.name, event.error_type, module)

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """에러 모니터링 루프를 실행한다."""
        self._running = True
        logger.info("에러 모니터링봇 시작")
        try:
            while not shutdown_event.is_set():
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self._REVIEW_INTERVAL,
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                if self._pending_errors:
                    await self._review_errors()
        except asyncio.CancelledError:
            logger.info("에러 모니터링봇 취소됨")
        finally:
            if self._pending_errors:
                await self._review_errors()
            self._running = False
            logger.info("에러 모니터링봇 종료")

    async def _review_errors(self) -> None:
        """수집된 에러를 그룹화하여 수리한다. 모듈+시간 기반으로 묶는다."""
        errors = self._pending_errors.copy()
        self._pending_errors.clear()

        # 모듈별로 그룹화한다
        groups = self._group_by_module(errors)

        for module, group_events in groups.items():
            # 그룹 내 가장 빈번한 에러를 대표로 선택한다
            type_counts = Counter(e.error_type for e in group_events)
            representative_type, count = type_counts.most_common(1)[0]
            representative = next(
                e for e in group_events if e.error_type == representative_type
            )

            logger.info(
                "에러 그룹 수리: module=%s, 유형=%s, 총 %d건 (대표: %s)",
                module, representative_type, len(group_events), representative_type,
            )

            result = await self._repair_manager.attempt_repair(representative)
            if result.success:
                self._total_repairs += 1
                logger.info("그룹 수리 성공: %s → %s", representative_type, result.action)
            else:
                logger.warning("그룹 수리 실패: %s → %s", representative_type, result.detail)

    def _group_by_module(
        self, errors: list[ErrorEvent],
    ) -> dict[str, list[ErrorEvent]]:
        """에러를 모듈+시간 윈도우로 그룹화한다."""
        groups: dict[str, list[ErrorEvent]] = defaultdict(list)
        for event in errors:
            groups[event.module].append(event)
        return dict(groups)

    async def manual_review(self) -> int:
        """수동 검토를 트리거한다. 검토한 에러 수를 반환한다."""
        count = len(self._pending_errors)
        if count > 0:
            await self._review_errors()
        return count

    def reset_session(self) -> None:
        """새 세션을 위해 모니터링 상태를 초기화한다."""
        self._pending_errors.clear()
        self._total_errors = 0
        self._total_repairs = 0
        self._repair_manager.reset_session()
        logger.info("ErrorMonitor 세션 초기화 완료")

    def get_status(self) -> dict[str, object]:
        """모니터링 상태를 반환한다."""
        return {
            "running": self._running,
            "pending_errors": len(self._pending_errors),
            "total_errors": self._total_errors,
            "total_repairs": self._total_repairs,
            "repair_manager": self._repair_manager.get_status(),
        }
