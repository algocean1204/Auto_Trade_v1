"""ExecutionOptimizer -- 거래 실행 결과를 분석하여 전략 파라미터를 자동 조정한다.

StrategyParamsManager를 사용하여 asyncio.Lock으로 동시 접근을 방지하고,
StrategyParams Pydantic 모델의 Field(ge=, le=) 범위 검증을 보장한다.
"""
from __future__ import annotations

import math

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.optimization.models import ExecutionOptimizerResult

logger = get_logger(__name__)

_MAX_ADJUST_PCT: float = 5.0


class ExecutionOptimizer:
    """거래 실행 성과를 분석하여 전략 파라미터를 +-5% 범위로 자동 조정한다."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    async def run(self) -> ExecutionOptimizerResult:
        """최적화를 실행한다. trades:today에서 당일 거래를 읽고 파라미터를 조정한다.

        StrategyParamsManager.async_update()를 사용하여
        파일 Lock + Pydantic 검증을 보장한다.
        """
        trades = await self._cache.read_json("trades:today") or []
        if not trades:
            logger.info("당일 거래 없음 — 최적화 건너뜀")
            return ExecutionOptimizerResult(
                adjusted_params={}, changes=[], backup_path="",
            )

        # StrategyParamsManager로 현재 파라미터를 로드한다
        from src.strategy.params.strategy_params import StrategyParamsManager
        mgr = StrategyParamsManager()
        current = mgr.load()
        changes: list[str] = []
        adjusted: dict = {}

        # 승률 기반 조정: 승률 > 60%이면 공격적, < 40%이면 보수적
        # NaN 방어: pnl 값이 유효한 숫자인 경우만 승리로 집계한다
        def _valid_pnl(t: dict) -> float:
            v = t.get("pnl") or 0
            try:
                f = float(v)
                return f if not (math.isnan(f) or math.isinf(f)) else 0.0
            except (ValueError, TypeError):
                return 0.0
        wins = sum(1 for t in trades if _valid_pnl(t) > 0)
        win_rate = wins / len(trades) if trades else 0.5

        updates: dict = {}

        if win_rate > 0.6:
            adj = min(_MAX_ADJUST_PCT, (win_rate - 0.5) * 20)
            old = current.default_position_size_pct
            new_val = round(old * (1 + adj / 100), 2)
            updates["default_position_size_pct"] = new_val
            adjusted["default_position_size_pct"] = new_val
            changes.append(f"position_size: {old} -> {new_val} (+{adj:.1f}%)")
        elif win_rate < 0.4:
            adj = min(_MAX_ADJUST_PCT, (0.5 - win_rate) * 20)
            old = current.default_position_size_pct
            new_val = round(old * (1 - adj / 100), 2)
            updates["default_position_size_pct"] = new_val
            adjusted["default_position_size_pct"] = new_val
            changes.append(f"position_size: {old} -> {new_val} (-{adj:.1f}%)")

        # 변경이 있으면 async_update로 Lock+Pydantic 검증을 거쳐 저장한다
        backup_path = ""
        if changes and updates:
            try:
                validated = await mgr.async_update(updates)
                # Pydantic이 클램핑한 실제 값으로 adjusted를 갱신한다
                for key in updates:
                    actual = getattr(validated, key, updates[key])
                    adjusted[key] = actual
                backup_path = mgr.get_path()
                logger.info("파라미터 조정 완료: %s", changes)
            except Exception as exc:
                logger.error("파라미터 저장 실패: %s", exc)
                changes.clear()
                adjusted.clear()
        else:
            logger.info("파라미터 조정 불필요 (승률=%.1f%%)", win_rate * 100)

        return ExecutionOptimizerResult(
            adjusted_params=adjusted,
            changes=changes,
            backup_path=backup_path,
        )
