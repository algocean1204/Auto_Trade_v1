"""F4 피라미딩 -- 3단계 추가 진입을 판단한다."""
from __future__ import annotations

from src.common.logger import get_logger
from src.strategy.models import Position, PyramidDecision, StrategyParams

logger = get_logger(__name__)

# 피라미딩 단계별 설정 (단계, 최소 수익률, 추가 비중%)
_PYRAMID_LEVELS: list[tuple[int, str, float]] = [
    (1, "pyramid_level1_pct", 50.0),
    (2, "pyramid_level2_pct", 30.0),
    (3, "pyramid_level3_pct", 20.0),
]

# 최대 피라미딩 레벨
_MAX_LEVEL = 3

# 허용 레짐
_ALLOWED_REGIMES = frozenset({"strong_bull", "mild_bull"})


def _get_threshold(level: int, params: StrategyParams) -> float:
    """단계별 최소 수익률 임계값을 반환한다."""
    thresholds = {
        1: params.pyramid_level1_pct,
        2: params.pyramid_level2_pct,
        3: params.pyramid_level3_pct,
    }
    if level not in thresholds:
        logger.error("유효하지 않은 피라미딩 레벨: %d (유효: 1-3) — 999.0 반환", level)
    return thresholds.get(level, 999.0)


def _get_add_size(level: int) -> float:
    """단계별 추가 비중을 반환한다."""
    for lv, _, size in _PYRAMID_LEVELS:
        if lv == level:
            return size
    return 0.0


def _calculate_ratchet_stop(position: Position, level: int) -> float:
    """래칫 스톱을 계산한다. 추가 진입 시 손절선을 올린다."""
    # 레벨이 올라갈수록 손절선을 평단가에 가깝게 설정한다
    base_stop_pct = -2.0
    ratchet_adjustment = level * 0.5
    return round(base_stop_pct + ratchet_adjustment, 2)


def _check_guards(
    position: Position,
    market_state: dict,
    params: StrategyParams,
) -> str | None:
    """8개 피라미딩 가드를 검사한다. 실패 시 사유를 반환한다."""
    # 1. 최대 레벨
    if position.pyramid_level >= _MAX_LEVEL:
        return f"최대 레벨 도달: {position.pyramid_level}/{_MAX_LEVEL}"

    # 2. 최소 수익
    next_level = position.pyramid_level + 1
    threshold = _get_threshold(next_level, params)
    if position.unrealized_pnl_pct < threshold:
        return f"수익률 부족: {position.unrealized_pnl_pct:.2f}% < {threshold}%"

    # 3. 리스크 예산 (포트폴리오 10% 이상 미달성)
    portfolio_risk = market_state.get("portfolio_risk_pct", 0.0)
    if portfolio_risk > 10.0:
        return f"리스크 예산 초과: {portfolio_risk:.1f}%"

    # 4. 집중도 (단일 티커 15% 초과 금지)
    concentration = market_state.get("ticker_concentration_pct", 0.0)
    if concentration > params.max_position_pct:
        return f"집중도 초과: {concentration:.1f}%"

    # 5. 레짐 확인
    regime_type = market_state.get("regime_type", "")
    if regime_type not in _ALLOWED_REGIMES:
        return f"레짐 부적합: {regime_type}"

    # 6. VIX 제한
    vix = market_state.get("vix", 30.0)
    if vix > 25.0:
        return f"VIX 과다: {vix:.1f}"

    # 7. 피라미딩 활성화 확인
    if not params.pyramiding_enabled:
        return "피라미딩 비활성화"

    # 8. Beast 포지션은 피라미딩 불가
    if position.is_beast:
        return "Beast 포지션은 피라미딩 불가"

    return None


class Pyramiding:
    """3단계 추가 진입을 판단한다."""

    def evaluate(
        self,
        position: Position,
        market_state: dict,
        params: StrategyParams,
    ) -> PyramidDecision:
        """피라미딩 가능 여부를 판단한다."""
        guard_fail = _check_guards(position, market_state, params)
        if guard_fail is not None:
            return PyramidDecision(should_add=False, reason=guard_fail)

        next_level = position.pyramid_level + 1
        add_size = _get_add_size(next_level)
        ratchet = _calculate_ratchet_stop(position, next_level)

        logger.info(
            "피라미딩 승인: %s level=%d add=%.1f%% ratchet=%.2f%%",
            position.ticker, next_level, add_size, ratchet,
        )

        return PyramidDecision(
            should_add=True,
            level=next_level,
            add_size_pct=add_size,
            ratchet_stop=ratchet,
            reason=f"레벨 {next_level} 진입 조건 충족",
        )
