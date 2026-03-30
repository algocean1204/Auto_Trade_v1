"""매매 감시봇 -- 일일 최소 매매를 감시하고 0건 거래 시 에스컬레이션한다.

체크포인트 스케줄(KST):
- 01:00 (2시간 경과): 0건 → 경고 + Tier2 level 1 (완만한 완화)
- 03:00 (4시간 경과): 0건 → Tier2 level 2 (공격적 완화)
- 05:00 (6시간 경과): 0건 → Tier3 (AI 분석 + 텔레그램 보고)
세션 종료 시 반드시 원래 임계값을 복원한다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.common.logger import get_logger
from src.healing.budget_tracker import BudgetTracker
from src.healing.tier2_config import relax_entry_thresholds, restore_thresholds
from src.orchestration.init.dependency_injector import InjectedSystem

logger: logging.Logger = get_logger(__name__)

# KST 체크포인트: (시각, 분, 에스컬레이션 레벨)
_CHECKPOINTS: list[tuple[int, int, int]] = [
    (1, 0, 1),   # 01:00 KST → level 1 완화
    (3, 0, 2),   # 03:00 KST → level 2 완화
    (5, 0, 3),   # 05:00 KST → tier 3 AI 분석
]

# 체크포인트 시각 판별 허용 오차 (분)
_CHECKPOINT_WINDOW_MIN: int = 5


class TradeWatchdog:
    """일일 최소 매매 감시봇이다. 0건 거래를 시스템 이상 신호로 판단한다."""

    def __init__(self, system: InjectedSystem) -> None:
        self._system = system
        self._running: bool = False
        self._relaxation_applied: int = 0  # 현재 적용된 완화 레벨
        self._trade_detected: bool = False
        self._budget = BudgetTracker()  # 세션 내 AI 호출 예산을 추적한다

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """매매 감시 루프를 실행한다. 60초마다 체크한다."""
        self._running = True
        logger.info("매매 감시봇 시작")
        try:
            while not shutdown_event.is_set():
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=60)
                    break  # shutdown 신호 수신
                except asyncio.TimeoutError:
                    pass  # 60초 경과 → 매매 건수 확인

                await self._check_trades()
        except asyncio.CancelledError:
            pass
        finally:
            # 세션 종료 시 임계값을 반드시 복원한다
            if self._relaxation_applied > 0:
                await restore_thresholds()
                logger.info("매매 감시봇: 임계값 원복 완료")
            self._budget.reset()  # 다음 세션을 위해 AI 호출 예산을 초기화한다
            self._running = False
            logger.info("매매 감시봇 종료")

    async def _check_trades(self) -> None:
        """현재 매매 건수를 확인하고 필요 시 에스컬레이션한다."""
        cache = self._system.components.cache
        trades_raw = await cache.read_json("trades:today")
        trade_count = len(trades_raw) if isinstance(trades_raw, list) else 0

        if trade_count > 0:
            self._trade_detected = True
            # 매매 성공 → 시스템 정상이므로 완화를 복원한다
            if self._relaxation_applied > 0:
                await restore_thresholds()
                self._relaxation_applied = 0
                logger.info("매매 감지 (%d건) → 임계값 원복", trade_count)
            return

        # 0건 거래 → KST 체크포인트 판별
        now_kst = datetime.now(ZoneInfo("Asia/Seoul"))

        for checkpoint_hour, checkpoint_min, level in _CHECKPOINTS:
            if now_kst.hour == checkpoint_hour and now_kst.minute < _CHECKPOINT_WINDOW_MIN:
                # 이미 해당 레벨 이상 적용되었으면 건너뛴다
                if self._relaxation_applied >= level:
                    continue
                await self._escalate(level, trade_count)
                break

    async def _escalate(self, level: int, trade_count: int) -> None:
        """레벨에 따라 Tier2 완화 또는 Tier3 AI 분석을 실행한다."""
        if level <= 2:
            # Tier2: 진입 임계값을 완화한다
            result = await relax_entry_thresholds(level=level)
            self._relaxation_applied = level
            logger.warning(
                "매매 감시: 0건 거래 → Tier2 완화 (level %d): %s", level, result.action,
            )
        else:
            # Tier3: AI 분석을 요청한다
            from src.healing.error_classifier import ErrorEvent, RepairTier
            from src.healing.tier3_analysis import attempt_tier3

            event = ErrorEvent(
                error_type="ZeroTrades",
                message=f"매매 세션 시작 후 {trade_count}건 거래 — 시스템 이상 의심",
                detail=f"relaxation_level={self._relaxation_applied}",
                timestamp=datetime.now(timezone.utc),
                module="trade_watchdog",
                tier=RepairTier.TIER3,
            )
            # 인스턴스 예산 추적기로 AI 분석을 실행한다 (세션 내 누적 추적)
            await attempt_tier3(self._system, [event], self._budget)
            logger.error("매매 감시: 0건 거래 → Tier3 AI 분석 요청")

    def get_status(self) -> dict[str, object]:
        """감시봇 상태를 반환한다."""
        return {
            "running": self._running,
            "trade_detected": self._trade_detected,
            "relaxation_level": self._relaxation_applied,
        }
