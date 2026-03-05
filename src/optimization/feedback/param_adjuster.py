"""FF 피드백 -- 성과 기반 파라미터 미세 조정이다."""

from __future__ import annotations

from src.common.logger import get_logger
from src.optimization.feedback.models import AdjustmentResult, DailyFeedbackResult

logger = get_logger(__name__)

# 조정 비율이다
_STEP_UP: float = 1.05
_STEP_DOWN: float = 0.95

# 승률 기준이다
_WIN_RATE_LOW: float = 0.4
_WIN_RATE_HIGH: float = 0.65

# PnL 기준이다
_PNL_NEGATIVE: float = 0.0


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전하게 float 변환한다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _adjust_value(
    current: float, multiplier: float,
) -> float:
    """값을 비율로 조정한다."""
    return round(current * multiplier, 6)


def _adjust_confidence(
    summary: dict, params: dict,
) -> tuple[dict, dict[str, dict] | None]:
    """승률에 따라 confidence를 조정한다."""
    key = "min_confidence"
    if key not in params:
        return params, None

    win_rate = _safe_float(summary.get("win_rate"))
    old_val = _safe_float(params[key])

    if win_rate < _WIN_RATE_LOW:
        new_val = _adjust_value(old_val, _STEP_UP)
        params[key] = new_val
        return params, {key: {"before": old_val, "after": new_val}}

    if win_rate > _WIN_RATE_HIGH:
        new_val = _adjust_value(old_val, _STEP_DOWN)
        params[key] = new_val
        return params, {key: {"before": old_val, "after": new_val}}

    return params, None


def _adjust_take_profit(
    summary: dict, params: dict,
) -> tuple[dict, dict[str, dict] | None]:
    """평균 PnL에 따라 익절 목표를 조정한다."""
    key = "take_profit_pct"
    if key not in params:
        return params, None

    avg_pnl = _safe_float(summary.get("avg_pnl"))
    old_val = _safe_float(params[key])

    if avg_pnl < _PNL_NEGATIVE:
        new_val = _adjust_value(old_val, _STEP_UP)
        params[key] = new_val
        return params, {key: {"before": old_val, "after": new_val}}

    return params, None


def _adjust_stop_loss(
    summary: dict, params: dict,
) -> tuple[dict, dict[str, dict] | None]:
    """최대 손실에 따라 손절을 조정한다."""
    key = "stop_loss_pct"
    if key not in params:
        return params, None

    max_loss = _safe_float(summary.get("max_loss"))
    old_val = _safe_float(params[key])

    # 최대 손실이 손절보다 크면 손절 강화이다
    if max_loss < old_val * -2:
        new_val = _adjust_value(old_val, _STEP_DOWN)
        params[key] = new_val
        return params, {key: {"before": old_val, "after": new_val}}

    return params, None


def _adjust_position_size(
    summary: dict, params: dict,
) -> tuple[dict, dict[str, dict] | None]:
    """총 PnL에 따라 포지션 크기를 조정한다."""
    key = "max_position_pct"
    if key not in params:
        return params, None

    total_pnl = _safe_float(summary.get("total_pnl"))
    old_val = _safe_float(params[key])

    if total_pnl < _PNL_NEGATIVE:
        new_val = _adjust_value(old_val, _STEP_DOWN)
        params[key] = new_val
        return params, {key: {"before": old_val, "after": new_val}}

    return params, None


def adjust_params(
    daily_result: DailyFeedbackResult,
    current_params: dict,
) -> AdjustmentResult:
    """일일 성과에 따라 전략 파라미터를 미세 조정한다.

    승률, 평균 PnL, 최대 손실, 총 PnL을 기준으로
    confidence, take_profit, stop_loss, position_size를 +-5% 조정한다.
    """
    logger.info("파라미터 조정 시작")

    params = {**current_params}
    summary = daily_result.summary
    adjusted_keys: list[str] = []
    before_after: dict[str, dict] = {}

    adjusters = [
        _adjust_confidence,
        _adjust_take_profit,
        _adjust_stop_loss,
        _adjust_position_size,
    ]

    for adjuster in adjusters:
        params, change = adjuster(summary, params)
        if change is not None:
            for k, v in change.items():
                adjusted_keys.append(k)
                before_after[k] = v

    logger.info("파라미터 조정 완료: %d건 변경", len(adjusted_keys))

    return AdjustmentResult(
        adjusted_keys=adjusted_keys,
        before_after=before_after,
    )
