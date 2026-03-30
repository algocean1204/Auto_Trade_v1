"""Self-Healing 패키지 -- 매매 시스템의 자동 에러 복구 모듈을 제공한다."""
from __future__ import annotations

from src.healing.error_classifier import ErrorEvent, RepairResult, RepairTier
from src.healing.error_monitor import ErrorMonitor
from src.healing.repair_cache import RepairCache
from src.healing.self_repair import SelfRepairManager
from src.healing.trade_watchdog import TradeWatchdog
from src.healing.budget_tracker import BudgetTracker

__all__ = [
    "RepairTier",
    "ErrorEvent",
    "RepairResult",
    "ErrorMonitor",
    "SelfRepairManager",
    "TradeWatchdog",
    "BudgetTracker",
    "RepairCache",
]
