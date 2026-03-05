"""F8 피드백 -- EOD 파라미터 +-5% 자동 조정이다."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from src.common.logger import get_logger
from src.optimization.models import ExecutionOptimizerResult

logger = get_logger(__name__)

# strategy_params.json 경로이다 (data/ 디렉터리 하위)
_PARAMS_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "strategy_params.json"
)
_BACKUP_DIR: Path = _PARAMS_PATH.parent / "param_backups"

# 조정 한도이다
_STEP_PCT: float = 0.05
_MAX_DEVIATION: float = 0.30


def _compute_win_rate(trades: list[dict]) -> float:
    """승률을 계산한다."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if _safe_float(t.get("pnl")) > 0)
    return wins / len(trades)


def _compute_avg_pnl_ratio(trades: list[dict]) -> float:
    """평균 손익비를 계산한다."""
    gains = [_safe_float(t.get("pnl")) for t in trades if _safe_float(t.get("pnl")) > 0]
    losses = [abs(_safe_float(t.get("pnl"))) for t in trades if _safe_float(t.get("pnl")) < 0]
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 1.0
    return avg_gain / avg_loss if avg_loss > 0 else 0.0


def _compute_avg_hold_minutes(trades: list[dict]) -> float:
    """평균 보유 시간(분)을 계산한다."""
    durations: list[float] = []
    for t in trades:
        dur = _safe_float(t.get("hold_minutes"))
        if dur > 0:
            durations.append(dur)
    return sum(durations) / len(durations) if durations else 0.0


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전한 float 변환이다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _apply_adjustment(
    current: float, direction: float, original: float,
) -> float:
    """+-5% 범위 내에서 파라미터를 조정한다. 최대 30% 이탈을 제한한다."""
    step = current * _STEP_PCT * direction
    new_val = current + step

    # 원래 값 대비 최대 이탈 제한이다
    lower = original * (1 - _MAX_DEVIATION)
    upper = original * (1 + _MAX_DEVIATION)
    return max(lower, min(upper, new_val))


def _backup_params() -> str:
    """현재 파라미터 파일을 백업한다."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = _BACKUP_DIR / f"strategy_params_{ts}.json"
    if _PARAMS_PATH.exists():
        shutil.copy2(_PARAMS_PATH, backup_path)
    return str(backup_path)


def _load_params() -> dict:
    """strategy_params.json을 로드한다."""
    if not _PARAMS_PATH.exists():
        return {}
    with open(_PARAMS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_params(params: dict) -> None:
    """strategy_params.json을 저장한다."""
    with open(_PARAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)


def _apply_rules(
    trades: list[dict], params: dict,
) -> tuple[dict, list[str]]:
    """6가지 규칙으로 파라미터를 조정한다."""
    changes: list[str] = []
    original = {**params}
    win_rate = _compute_win_rate(trades)
    pnl_ratio = _compute_avg_pnl_ratio(trades)
    avg_hold = _compute_avg_hold_minutes(trades)

    # 규칙 1: 승률 50% 미만 → confidence 상향이다
    if win_rate < 0.5 and "min_confidence" in params:
        old = params["min_confidence"]
        params["min_confidence"] = _apply_adjustment(old, 1.0, original.get("min_confidence", old))
        changes.append(f"승률 {win_rate:.1%} < 50% → min_confidence {old:.3f} → {params['min_confidence']:.3f}")

    # 규칙 2: 승률 70% 초과 → confidence 하향이다
    if win_rate > 0.7 and "min_confidence" in params:
        old = params["min_confidence"]
        params["min_confidence"] = _apply_adjustment(old, -1.0, original.get("min_confidence", old))
        changes.append(f"승률 {win_rate:.1%} > 70% → min_confidence {old:.3f} → {params['min_confidence']:.3f}")

    # 규칙 3: 손익비 1.0 미만 → take_profit 상향이다
    if pnl_ratio < 1.0 and "take_profit_pct" in params:
        old = params["take_profit_pct"]
        params["take_profit_pct"] = _apply_adjustment(old, 1.0, original.get("take_profit_pct", old))
        changes.append(f"손익비 {pnl_ratio:.2f} < 1.0 → take_profit {old:.3f} → {params['take_profit_pct']:.3f}")

    # 규칙 4: 평균 보유 5분 미만 → trailing 완화이다
    if avg_hold < 5 and "trailing_stop_pct" in params:
        old = params["trailing_stop_pct"]
        params["trailing_stop_pct"] = _apply_adjustment(old, 1.0, original.get("trailing_stop_pct", old))
        changes.append(f"보유 {avg_hold:.0f}분 < 5분 → trailing {old:.3f} → {params['trailing_stop_pct']:.3f}")

    # 규칙 5: 평균 보유 30분 초과 → trailing 강화이다
    if avg_hold > 30 and "trailing_stop_pct" in params:
        old = params["trailing_stop_pct"]
        params["trailing_stop_pct"] = _apply_adjustment(old, -1.0, original.get("trailing_stop_pct", old))
        changes.append(f"보유 {avg_hold:.0f}분 > 30분 → trailing {old:.3f} → {params['trailing_stop_pct']:.3f}")

    # 규칙 6: 전체 PnL 음수 → position_size 축소이다
    total_pnl = sum(_safe_float(t.get("pnl")) for t in trades)
    if total_pnl < 0 and "max_position_pct" in params:
        old = params["max_position_pct"]
        params["max_position_pct"] = _apply_adjustment(old, -1.0, original.get("max_position_pct", old))
        changes.append(f"PnL ${total_pnl:.2f} < 0 → max_position {old:.3f} → {params['max_position_pct']:.3f}")

    return params, changes


def optimize_execution(
    daily_trades: list[dict],
    current_params: dict | None = None,
) -> ExecutionOptimizerResult:
    """EOD 거래 분석으로 파라미터를 +-5% 자동 조정한다.

    6가지 규칙을 적용하여 승률, 손익비, 보유시간에 따라
    파라미터를 미세 조정한다. 최대 30% 이탈을 제한한다.
    """
    # 파라미터 로드이다
    params = current_params if current_params is not None else _load_params()
    backup_path = _backup_params()

    logger.info("실행 최적화 시작: %d trades, backup=%s", len(daily_trades), backup_path)

    adjusted, changes = _apply_rules(daily_trades, {**params})

    if changes:
        _save_params(adjusted)
        logger.info("파라미터 조정 완료: %d건", len(changes))
    else:
        logger.info("조정 필요 없음")

    return ExecutionOptimizerResult(
        adjusted_params=adjusted,
        changes=changes,
        backup_path=backup_path,
    )
