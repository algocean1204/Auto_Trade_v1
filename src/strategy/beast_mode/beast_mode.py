"""F4 Beast Mode -- A+ 셋업 고확신 매매를 판단한다."""
from __future__ import annotations

import time

from src.analysis.models import MarketRegime
from src.common.logger import get_logger
from src.strategy.models import BeastDecision, StrategyParams

logger = get_logger(__name__)

# 가중치 상수
_W_CONFIDENCE = 0.30
_W_OBI = 0.25
_W_LEADER = 0.20
_W_VOLUME = 0.15
_W_WHALE = 0.10

# 컨빅션 배율 범위
_CONVICTION_MIN = 2.5
_CONVICTION_MAX = 3.0

# 허용 레짐
_ALLOWED_REGIMES = frozenset({"strong_bull", "mild_bull"})
_VIX_LIMIT = 25.0


def _check_a_plus_setup(
    confidence: float,
    obi_score: float,
    leader_momentum: float,
    volume_ratio: float,
    whale_alignment: bool,
    params: StrategyParams,
) -> bool:
    """A+ 셋업 AND 조건을 검증한다. 모두 충족해야 True를 반환한다."""
    return (
        confidence > params.beast_min_confidence
        and obi_score > params.beast_min_obi
        and leader_momentum > 0.6
        and volume_ratio >= 2.0
        and whale_alignment
    )


def _compute_composite(
    confidence: float,
    obi_score: float,
    leader_momentum: float,
    volume_ratio: float,
    whale_alignment: bool,
) -> float:
    """가중 합성 점수를 계산한다."""
    whale_val = 1.0 if whale_alignment else 0.0
    # 볼륨 비율은 0~1 범위로 정규화한다 (최대 5x)
    volume_norm = min(volume_ratio / 5.0, 1.0)
    score = (
        _W_CONFIDENCE * min(confidence, 1.0)
        + _W_OBI * min(obi_score, 1.0)
        + _W_LEADER * min(leader_momentum, 1.0)
        + _W_VOLUME * volume_norm
        + _W_WHALE * whale_val
    )
    return round(score, 4)


def _interpolate_conviction(composite: float) -> float:
    """합성 점수 0.8~1.0 범위에서 컨빅션 2.5x~3.0x를 선형 보간한다."""
    if composite <= 0.8:
        return _CONVICTION_MIN
    if composite >= 1.0:
        return _CONVICTION_MAX
    ratio = (composite - 0.8) / 0.2
    return round(_CONVICTION_MIN + ratio * (_CONVICTION_MAX - _CONVICTION_MIN), 2)


def _check_guards(
    regime: MarketRegime,
    vix: float,
    daily_beast_count: int,
    last_failure_time: float | None,
    params: StrategyParams,
) -> str | None:
    """Beast Mode 가드를 검사한다. 실패 시 사유 문자열을 반환한다."""
    if regime.regime_type not in _ALLOWED_REGIMES:
        return f"레짐 부적합: {regime.regime_type}"
    if vix >= _VIX_LIMIT:
        return f"VIX 과다: {vix:.1f}"
    if daily_beast_count >= params.beast_max_daily:
        return f"일일 한도 초과: {daily_beast_count}/{params.beast_max_daily}"
    if last_failure_time is not None:
        elapsed = time.time() - last_failure_time
        if elapsed < params.beast_cooldown_seconds:
            return f"쿨다운 중: {int(elapsed)}s/{params.beast_cooldown_seconds}s"
    return None


class BeastMode:
    """A+ 셋업 고확신 매매를 판단한다."""

    def evaluate(
        self,
        confidence: float,
        obi_score: float,
        leader_momentum: float,
        volume_ratio: float,
        whale_alignment: bool,
        regime: MarketRegime,
        vix: float,
        params: StrategyParams,
        daily_beast_count: int = 0,
        last_failure_time: float | None = None,
    ) -> BeastDecision:
        """Beast Mode 활성화 여부를 판단한다."""
        if not params.beast_mode_enabled:
            return BeastDecision(activated=False, rejection_reason="Beast Mode 비활성화")

        # 가드 체크
        guard_fail = _check_guards(regime, vix, daily_beast_count, last_failure_time, params)
        if guard_fail is not None:
            return BeastDecision(activated=False, rejection_reason=guard_fail)

        # A+ 셋업 검증
        is_a_plus = _check_a_plus_setup(
            confidence, obi_score, leader_momentum, volume_ratio, whale_alignment, params,
        )
        if not is_a_plus:
            return BeastDecision(activated=False, rejection_reason="A+ 셋업 미충족")

        composite = _compute_composite(confidence, obi_score, leader_momentum, volume_ratio, whale_alignment)
        conviction = _interpolate_conviction(composite)
        size = round(params.default_position_size_pct * conviction, 2)

        logger.info("Beast Mode 활성화: composite=%.4f conviction=%.2fx size=%.2f%%", composite, conviction, size)

        return BeastDecision(
            activated=True,
            conviction_multiplier=conviction,
            ego_type="cold_blooded_sniper",
            position_size_pct=min(size, params.max_position_pct),
            composite_score=composite,
        )
