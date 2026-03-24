"""F8 피드백 -- EOD 파라미터 +-5% 자동 조정이다.

StrategyParamsManager를 통해 Pydantic 검증과 파일 Lock을 보장한다.
규칙 1~5(min_confidence, take_profit_pct, trailing_stop_pct)는
strategy_params.json에 해당 키가 없으므로 strategy_params.json 내
실제 존재하는 키만 조정한다.
"""

from __future__ import annotations

import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir
from src.optimization.models import ExecutionOptimizerResult

logger = get_logger(__name__)

# 경로 함수 -- 호출 시점에 평가하여 번들/개발 모드 분기를 보장한다
def _params_path() -> Path:
    """strategy_params.json 경로를 반환한다."""
    return get_data_dir() / "strategy_params.json"


def _backup_dir() -> Path:
    """파라미터 백업 디렉토리를 반환한다."""
    return get_data_dir() / "param_backups"

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


def _safe_float(val: float | str | None, default: float = 0.0) -> float:
    """안전한 float 변환이다. NaN/inf이면 기본값을 반환한다."""
    if val is None:
        return default
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
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
    bk_dir = _backup_dir()
    bk_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = bk_dir / f"strategy_params_{ts}.json"
    pp = _params_path()
    if pp.exists():
        shutil.copy2(pp, backup_path)
    return str(backup_path)


def _apply_rules(
    trades: list[dict], params: dict,
) -> tuple[dict, list[str]]:
    """strategy_params.json에 실제 존재하는 키만 조정한다.

    규칙 1~5(min_confidence, take_profit_pct, trailing_stop_pct)는
    per-ticker 파라미터(ticker_params.json)에만 존재하므로
    strategy_params.json에서는 건너뛰고 로그로 알린다.
    규칙 6~8(max_position_pct, min_exit_qty, small_position_trailing_multiplier)는
    strategy_params.json에 존재하므로 정상 조정한다.
    """
    # 거래가 없으면 조정 근거가 없으므로 즉시 반환한다
    # (빈 리스트로 win_rate=0, pnl_ratio=0, avg_hold=0이 산출되어 허위 신호가 발생한다)
    if not trades:
        return params, []

    changes: list[str] = []
    original = {**params}
    win_rate = _compute_win_rate(trades)
    pnl_ratio = _compute_avg_pnl_ratio(trades)
    avg_hold = _compute_avg_hold_minutes(trades)

    # 규칙 1-2: 승률 기반 beast_min_confidence 조정
    # (beast_min_confidence는 strategy_params.json에 존재한다)
    if win_rate < 0.5 and "beast_min_confidence" in params:
        old = params["beast_min_confidence"]
        new_val = _apply_adjustment(old, 1.0, original.get("beast_min_confidence", old))
        # Pydantic ge=0.0, le=1.0 범위 클램핑
        new_val = max(0.0, min(1.0, new_val))
        params["beast_min_confidence"] = round(new_val, 4)
        changes.append(
            f"승률 {win_rate:.1%} < 50% → beast_min_confidence {old:.3f} → {params['beast_min_confidence']:.3f}",
        )
    elif win_rate > 0.7 and "beast_min_confidence" in params:
        old = params["beast_min_confidence"]
        new_val = _apply_adjustment(old, -1.0, original.get("beast_min_confidence", old))
        new_val = max(0.0, min(1.0, new_val))
        params["beast_min_confidence"] = round(new_val, 4)
        changes.append(
            f"승률 {win_rate:.1%} > 70% → beast_min_confidence {old:.3f} → {params['beast_min_confidence']:.3f}",
        )

    # 규칙 3: 손익비 < 1.0 → friction_hurdle 상향 (take_profit_pct는 strategy_params에 없음)
    if pnl_ratio < 1.0 and "friction_hurdle" in params:
        old = params["friction_hurdle"]
        new_val = _apply_adjustment(old, 1.0, original.get("friction_hurdle", old))
        # Pydantic ge=0.0, le=5.0 범위 클램핑
        new_val = max(0.0, min(5.0, new_val))
        params["friction_hurdle"] = round(new_val, 4)
        if params["friction_hurdle"] != old:
            changes.append(
                f"손익비 {pnl_ratio:.2f} < 1.0 → friction_hurdle {old:.3f} → {params['friction_hurdle']:.3f}",
            )

    # 규칙 4-5: 평균 보유시간 기반 → obi_threshold 조정
    # (trailing_stop_pct는 strategy_params.json에 없으므로 obi_threshold를 대리 조정한다)
    if avg_hold < 5 and "obi_threshold" in params:
        old = params["obi_threshold"]
        # 보유시간이 너무 짧으면 진입 문턱을 높인다
        new_val = _apply_adjustment(old, 1.0, original.get("obi_threshold", old))
        new_val = max(0.0, min(1.0, new_val))
        params["obi_threshold"] = round(new_val, 4)
        if params["obi_threshold"] != old:
            changes.append(
                f"보유 {avg_hold:.0f}분 < 5분 → obi_threshold {old:.3f} → {params['obi_threshold']:.3f}",
            )

    # 규칙 6: 전체 PnL 음수 → max_position_pct 축소이다
    total_pnl = sum(_safe_float(t.get("pnl")) for t in trades)
    if total_pnl < 0 and "max_position_pct" in params:
        old = params["max_position_pct"]
        new_val = _apply_adjustment(old, -1.0, original.get("max_position_pct", old))
        # Pydantic ge=0.1, le=100.0 범위 클램핑
        new_val = max(0.1, min(100.0, new_val))
        params["max_position_pct"] = round(new_val, 4)
        changes.append(f"PnL ${total_pnl:.2f} < 0 → max_position {old:.3f} → {params['max_position_pct']:.3f}")

    # 규칙 7: 소량 매도(min_exit_qty 이하)가 3건 이상 → min_exit_qty 상향이다
    small_exits = sum(
        1 for t in trades
        if _safe_float(t.get("quantity", 0)) <= params.get("min_exit_qty", 5)
        and _safe_float(t.get("quantity", 0)) > 0
    )
    if small_exits >= 3 and "min_exit_qty" in params:
        old = params["min_exit_qty"]
        # Pydantic ge=1, le=100 범위 클램핑 (최대 10으로 비즈니스 제한)
        params["min_exit_qty"] = min(old + 1, 10)
        if params["min_exit_qty"] != old:
            changes.append(f"소량 매도 {small_exits}건 >= 3 → min_exit_qty {old} → {params['min_exit_qty']}")

    # 규칙 8: 트레일링 조기 청산 수익 구간에서 발생 → multiplier 상향이다
    small_trail_exits = sum(
        1 for t in trades
        if t.get("exit_type") == "trailing_stop"
        and _safe_float(t.get("quantity", 0)) <= params.get("min_exit_qty", 5)
        and _safe_float(t.get("pnl", 0)) > 0
    )
    if small_trail_exits >= 2 and "small_position_trailing_multiplier" in params:
        old = params["small_position_trailing_multiplier"]
        # Pydantic ge=0.1, le=10.0 범위 클램핑 (최대 2.5로 비즈니스 제한)
        params["small_position_trailing_multiplier"] = min(round(old + 0.1, 1), 2.5)
        if params["small_position_trailing_multiplier"] != old:
            changes.append(
                f"소량 트레일링 청산 {small_trail_exits}건 → "
                f"multiplier {old:.1f} → {params['small_position_trailing_multiplier']:.1f}",
            )

    return params, changes


def optimize_execution(
    daily_trades: list[dict],
    current_params: dict | None = None,
) -> ExecutionOptimizerResult:
    """EOD 거래 분석으로 파라미터를 +-5% 자동 조정한다.

    StrategyParamsManager를 통해 Pydantic 검증을 거쳐 저장한다.
    Field(ge=, le=) 범위를 초과하는 값은 Pydantic이 거부하므로
    조정 결과가 범위 내에 있음을 보장한다.
    """
    from src.strategy.params.strategy_params import StrategyParamsManager
    mgr = StrategyParamsManager()

    # 파라미터 로드이다 -- Pydantic 모델이 아닌 raw dict로 로드한다
    # (조정 대상 키가 Pydantic 필드가 아닌 경우도 있기 때문이다)
    if current_params is not None:
        params = current_params
    else:
        loaded = mgr.load()
        params = loaded.model_dump()

    backup_path = _backup_params()
    logger.info("실행 최적화 시작: %d trades, backup=%s", len(daily_trades), backup_path)

    adjusted, changes = _apply_rules(daily_trades, {**params})

    if changes:
        # StrategyParamsManager.update()를 통해 Pydantic 검증 후 저장한다
        try:
            validated = mgr.update(adjusted)
            logger.info("파라미터 조정 완료: %d건 (Pydantic 검증 통과)", len(changes))
            # Pydantic이 클램핑한 실제 값을 반영한다
            adjusted = validated.model_dump()
        except Exception as exc:
            logger.error("Pydantic 검증 실패 — 원본 유지: %s", exc)
            changes.clear()
            adjusted = params
    else:
        logger.info("조정 필요 없음")

    return ExecutionOptimizerResult(
        adjusted_params=adjusted,
        changes=changes,
        backup_path=backup_path,
    )
