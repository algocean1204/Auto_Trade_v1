"""ExecutionOptimizer -- 거래 실행 결과를 분석하여 전략 파라미터를 자동 조정한다."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.optimization.models import ExecutionOptimizerResult

logger = get_logger(__name__)

_PARAMS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "strategy_params.json"
_MAX_ADJUST_PCT: float = 5.0


class ExecutionOptimizer:
    """거래 실행 성과를 분석하여 전략 파라미터를 +-5% 범위로 자동 조정한다."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    async def run(self) -> ExecutionOptimizerResult:
        """최적화를 실행한다. trades:today에서 당일 거래를 읽고 파라미터를 조정한다."""
        trades = await self._cache.read_json("trades:today") or []
        if not trades:
            logger.info("당일 거래 없음 — 최적화 건너뜀")
            return ExecutionOptimizerResult(
                adjusted_params={}, changes=[], backup_path="",
            )

        # 현재 파라미터를 로드한다
        params = self._load_params()
        changes: list[str] = []
        adjusted: dict = {}

        # 승률 기반 조정: 승률 > 60%이면 공격적, < 40%이면 보수적
        wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
        win_rate = wins / len(trades) if trades else 0.5

        if win_rate > 0.6:
            adj = min(_MAX_ADJUST_PCT, (win_rate - 0.5) * 20)
            if "default_position_size_pct" in params:
                old = params["default_position_size_pct"]
                new_val = round(old * (1 + adj / 100), 2)
                params["default_position_size_pct"] = new_val
                adjusted["default_position_size_pct"] = new_val
                changes.append(f"position_size: {old} -> {new_val} (+{adj:.1f}%)")
        elif win_rate < 0.4:
            adj = min(_MAX_ADJUST_PCT, (0.5 - win_rate) * 20)
            if "default_position_size_pct" in params:
                old = params["default_position_size_pct"]
                new_val = round(old * (1 - adj / 100), 2)
                params["default_position_size_pct"] = new_val
                adjusted["default_position_size_pct"] = new_val
                changes.append(f"position_size: {old} -> {new_val} (-{adj:.1f}%)")

        # 변경이 있으면 저장한다
        backup_path = ""
        if changes:
            backup_path = self._backup_and_save(params)
            logger.info("파라미터 조정 완료: %s", changes)
        else:
            logger.info("파라미터 조정 불필요 (승률=%.1f%%)", win_rate * 100)

        return ExecutionOptimizerResult(
            adjusted_params=adjusted,
            changes=changes,
            backup_path=backup_path,
        )

    def _load_params(self) -> dict:
        """strategy_params.json을 로드한다."""
        if not _PARAMS_PATH.exists():
            return {}
        try:
            return json.loads(_PARAMS_PATH.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("파라미터 파일 로드 실패")
            return {}

    def _backup_and_save(self, params: dict) -> str:
        """백업 후 파라미터를 저장한다."""
        import shutil
        backup_name = ""
        if _PARAMS_PATH.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"strategy_params_{ts}.json"
            backup_path = _PARAMS_PATH.parent / backup_name
            shutil.copy2(_PARAMS_PATH, backup_path)
        _PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PARAMS_PATH.write_text(
            json.dumps(params, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return backup_name
