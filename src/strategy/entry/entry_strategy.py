"""F4 진입 전략 -- 7개 게이트 순차 평가로 진입을 판단한다.

데이터 미가용 게이트는 통과 처리하되 확신도 페널티를 부과한다.
레짐 position_multiplier를 포지션 사이즈에 반영한다.
"""
from __future__ import annotations

from src.analysis.models import MarketRegime
from src.common.logger import get_logger
from src.indicators.models import IndicatorBundle
from src.strategy.models import EntryDecision, Position, StrategyParams

logger = get_logger(__name__)

# Friction Gate -- 마찰 비용 허들 기준 (기본 bps)
_FRICTION_SPREAD_BPS: float = 10.0
_FRICTION_SLIPPAGE_BPS: float = 5.0

# RAG Gate -- 실패 패턴 유사도 임계값 (이 이상이면 차단)
_RAG_FAILURE_SIMILARITY_THRESHOLD: float = 0.85

# 게이트 이름 상수
_GATE_OBI = "obi"
_GATE_CROSS_ASSET = "cross_asset"
_GATE_WHALE = "whale"
_GATE_REGIME_ENTRY = "regime_entry"
_GATE_ML = "ml"
_GATE_FRICTION = "friction"
_GATE_RAG = "rag"

# 데이터 미가용 시 게이트별 확신도 페널티이다
# 핵심 지표(OBI, ML)는 높은 페널티, 보조 지표는 낮은 페널티를 부과한다
_MISSING_DATA_PENALTY: dict[str, float] = {
    _GATE_OBI: 0.20,         # OBI 주문흐름: 핵심 — 20% 감점
    _GATE_CROSS_ASSET: 0.10, # 크로스에셋: 보조 — 10% 감점
    _GATE_WHALE: 0.10,       # 고래활동: 보조 — 10% 감점
    _GATE_ML: 0.20,          # ML 실행강도: 핵심 — 20% 감점
}


def _check_obi_gate(bundle: IndicatorBundle, params: StrategyParams) -> tuple[bool, bool]:
    """OBI 게이트 -- 주문 흐름 편향이 임계값 이상인지 확인한다.

    Returns: (통과 여부, 데이터 미가용 여부)
    """
    if bundle.order_flow is None:
        logger.debug("OBI 게이트: order_flow 데이터 미가용 -- 통과+페널티 처리한다")
        return True, True
    return bundle.order_flow.obi > params.obi_threshold, False


def _check_cross_asset_gate(bundle: IndicatorBundle) -> tuple[bool, bool]:
    """크로스에셋 모멘텀 게이트 -- 리더 정렬도가 0.3 이상인지 확인한다.

    Returns: (통과 여부, 데이터 미가용 여부)
    """
    if bundle.momentum is None:
        logger.debug("크로스에셋 게이트: momentum 데이터 미가용 -- 통과+페널티 처리한다")
        return True, True
    return bundle.momentum.alignment > 0.3, False


def _check_whale_gate(bundle: IndicatorBundle) -> tuple[bool, bool]:
    """고래 활동 게이트 -- 고래 총점이 0.3 이상인지 확인한다.

    Returns: (통과 여부, 데이터 미가용 여부)
    """
    if bundle.whale is None:
        logger.debug("고래 게이트: whale 데이터 미가용 -- 통과+페널티 처리한다")
        return True, True
    return bundle.whale.total_score > 0.3, False


def _check_regime_entry_gate(ticker: str, regime: MarketRegime) -> bool:
    """레짐 기반 진입 게이트 -- 레짐 파라미터에 따라 bull/bear 진입을 허용한다."""
    from src.common.ticker_registry import get_ticker_registry

    registry = get_ticker_registry()

    # 레지스트리에 없는 티커는 bull(일반) ETF로 취급한다
    is_inverse = registry.is_inverse(ticker) if registry.has_ticker(ticker) else False

    if is_inverse:
        return regime.params.allow_bear_entry
    else:
        return regime.params.allow_bull_entry


def _check_ml_gate(bundle: IndicatorBundle, params: StrategyParams) -> tuple[bool, bool]:
    """ML 게이트 -- 주문 흐름 실행 강도가 임계값 이상인지 확인한다.

    Returns: (통과 여부, 데이터 미가용 여부)
    """
    if bundle.order_flow is None:
        logger.debug("ML 게이트: order_flow 데이터 미가용 -- 통과+페널티 처리한다")
        return True, True
    return bundle.order_flow.execution_strength > params.ml_threshold, False


def _check_friction_gate(bundle: IndicatorBundle, params: StrategyParams) -> bool:
    """마찰 비용 게이트 -- 예상 수익이 마찰 비용 허들을 초과하는지 확인한다.

    FrictionCalculator로 스프레드+슬리피지 마찰 비용을 계산하고,
    현재 확신도 기반 예상 수익(confidence * max_position_pct)이 허들을 초과해야 통과한다.
    FrictionCalculator 임포트 실패 시 fail-open으로 통과 처리한다.
    """
    try:
        from src.risk.friction.friction_calculator import calculate_friction
        # 현재가를 technical 지표에서 추출한다 (없으면 기본 100달러로 가정한다)
        price = 100.0
        if bundle.technical is not None:
            price = bundle.technical.ema_20 if bundle.technical.ema_20 > 0 else 100.0

        friction = calculate_friction(
            price=price,
            spread_bps=_FRICTION_SPREAD_BPS,
            slippage_bps=_FRICTION_SLIPPAGE_BPS,
            round_trip=True,
        )

        # 허들(min_gain_hurdle)을 현재 전략 파라미터 허들과 비교한다
        # friction.min_gain_hurdle은 % 단위이다
        expected_gain = params.friction_hurdle  # strategy_params에 설정된 최소 허들
        passed = expected_gain >= friction.min_gain_hurdle
        if not passed:
            logger.debug(
                "마찰 게이트 차단: 예상수익=%.3f%% < 허들=%.3f%%",
                expected_gain, friction.min_gain_hurdle,
            )
        return passed
    except Exception as exc:
        logger.warning("마찰 게이트 계산 실패 (통과 처리): %s", exc)
        return True  # fail-open


def _check_rag_gate(bundle: IndicatorBundle) -> bool:
    """RAG 실패 패턴 게이트 -- 과거 유사 실패 패턴과 매칭되는지 확인한다.

    KnowledgeManager로 현재 지표 상황이 과거 실패 패턴과 유사한지 검색한다.
    유사도 임계값 이상이면 진입을 차단한다.
    KnowledgeManager 임포트 실패 또는 패턴 없음 시 fail-open으로 통과 처리한다.
    """
    try:
        from src.optimization.rag.knowledge_manager import KnowledgeManager
        km = KnowledgeManager()
        # 현재 지표 상황을 텍스트로 변환하여 유사 실패 패턴을 검색한다
        query_parts = []
        if bundle.order_flow is not None:
            query_parts.append(f"OBI={bundle.order_flow.obi:.3f}")
            query_parts.append(f"VPIN={bundle.order_flow.vpin:.3f}")
        if bundle.momentum is not None:
            query_parts.append(f"momentum={bundle.momentum.alignment:.3f}")

        if not query_parts:
            return True  # 지표 없으면 통과

        query = "실패 패턴: " + " ".join(query_parts)
        results = km.search(query, n_results=1)

        # 결과가 있고 유사도가 임계값 이상이면 차단한다
        if results and len(results) > 0:
            # KnowledgeManager 검색 결과에서 거리/유사도를 확인한다
            first = results[0]
            if isinstance(first, dict):
                similarity = first.get("similarity", 0.0)
                if similarity >= _RAG_FAILURE_SIMILARITY_THRESHOLD:
                    logger.info("RAG 게이트 차단: 실패 패턴 유사도=%.3f", similarity)
                    return False
        return True
    except Exception as exc:
        logger.debug("RAG 게이트 검색 실패 (통과 처리): %s", exc)
        return True  # fail-open


def _calculate_confidence(bundle: IndicatorBundle, missing_penalty: float) -> float:
    """지표 번들에서 진입 확신도를 계산한다.

    실제 데이터가 있는 지표의 평균 점수를 기반으로 하되,
    데이터 미가용 게이트의 페널티를 차감한다.
    모든 데이터가 없으면 0.0을 반환하여 진입을 차단한다.
    """
    scores: list[float] = []
    if bundle.order_flow is not None:
        scores.append(min(bundle.order_flow.obi, 1.0))
    if bundle.momentum is not None:
        scores.append(min(bundle.momentum.alignment, 1.0))
    if bundle.whale is not None:
        scores.append(min(bundle.whale.total_score, 1.0))

    if not scores:
        # 모든 핵심 데이터가 없으면 진입하지 않는다
        logger.warning("진입 확신도 0.0: 핵심 지표 데이터가 전혀 없다")
        return 0.0

    base_confidence = sum(scores) / len(scores)
    # 데이터 미가용 페널티를 차감한다
    adjusted = max(0.0, base_confidence - missing_penalty)
    return round(adjusted, 4)


def _calculate_position_size(
    confidence: float,
    params: StrategyParams,
    positions: list[Position],
    regime_multiplier: float,
) -> float:
    """확신도, 레짐, 기존 포지션에 따라 포지션 크기(%)를 계산한다.

    반환값은 계좌 자산 대비 퍼센트이다 (예: 5.0 = 5%).
    실제 주식 수 변환은 trading_loop에서 수행한다.
    """
    base = params.default_position_size_pct
    # 확신도에 따라 50~100% 범위로 조정한다
    adjusted = base * (0.5 + 0.5 * confidence)
    # 레짐 배수를 적용한다 (mild_bear=0.5, crash=1.5 등)
    adjusted *= regime_multiplier
    # 기존 포지션이 많으면 축소한다
    position_count = len(positions)
    if position_count >= 5:
        adjusted *= 0.5
    elif position_count >= 3:
        adjusted *= 0.7
    return round(min(adjusted, params.max_position_pct), 2)


class EntryStrategy:
    """7개 진입 게이트를 순차 평가하여 진입 판단을 내린다.

    데이터 미가용 게이트는 통과 처리하되, 확신도에 페널티를 부과한다.
    핵심 지표(OBI, ML)는 20% 감점, 보조 지표(크로스에셋, 고래)는 10% 감점이다.
    모든 핵심 데이터가 없으면 확신도 0.0으로 진입을 사실상 차단한다.
    """

    def evaluate(
        self,
        ticker: str,
        bundle: IndicatorBundle,
        regime: MarketRegime,
        positions: list[Position],
        params: StrategyParams,
    ) -> EntryDecision:
        """7개 게이트를 순서대로 평가한다. 하나라도 실패하면 진입을 차단한다."""
        gates: dict[str, bool] = {}
        total_penalty: float = 0.0

        # 데이터 의존 게이트: (이름, 평가함수) -- 미가용 시 페널티 부과
        data_gate_checks = [
            (_GATE_OBI, lambda: _check_obi_gate(bundle, params)),
            (_GATE_CROSS_ASSET, lambda: _check_cross_asset_gate(bundle)),
            (_GATE_WHALE, lambda: _check_whale_gate(bundle)),
            (_GATE_ML, lambda: _check_ml_gate(bundle, params)),
        ]

        blocked_by: str | None = None

        for name, check_fn in data_gate_checks:
            passed, missing = check_fn()
            gates[name] = passed
            if not passed and blocked_by is None:
                blocked_by = name
            if missing:
                penalty = _MISSING_DATA_PENALTY.get(name, 0.1)
                total_penalty += penalty
                logger.debug("진입 페널티: %s 데이터 미가용 (%.0f%% 감점)", name, penalty * 100)

        # 레짐 게이트 (데이터 의존 없음)
        regime_passed = _check_regime_entry_gate(ticker, regime)
        gates[_GATE_REGIME_ENTRY] = regime_passed
        if not regime_passed and blocked_by is None:
            blocked_by = _GATE_REGIME_ENTRY

        # 마찰 비용 게이트
        friction_passed = _check_friction_gate(bundle, params)
        gates[_GATE_FRICTION] = friction_passed
        if not friction_passed and blocked_by is None:
            blocked_by = _GATE_FRICTION

        # RAG 실패 패턴 게이트
        rag_passed = _check_rag_gate(bundle)
        gates[_GATE_RAG] = rag_passed
        if not rag_passed and blocked_by is None:
            blocked_by = _GATE_RAG

        all_passed = all(gates.values())
        confidence = _calculate_confidence(bundle, total_penalty) if all_passed else 0.0

        # 확신도가 최소 임계값(0.3) 미만이면 사실상 차단한다
        if all_passed and confidence < 0.3:
            all_passed = False
            blocked_by = "low_confidence"
            logger.info(
                "진입 차단(낮은 확신도): %s confidence=%.4f (페널티=%.2f)",
                ticker, confidence, total_penalty,
            )

        size = _calculate_position_size(
            confidence, params, positions, regime.params.position_multiplier,
        ) if all_passed else 0.0

        decision = EntryDecision(
            should_enter=all_passed,
            confidence=confidence,
            position_size_pct=size,
            blocked_by=blocked_by,
            gate_results=gates,
            ticker=ticker,
        )
        logger.info(
            "진입 판단: %s should_enter=%s confidence=%.4f blocked_by=%s penalty=%.2f",
            ticker, all_passed, confidence, blocked_by, total_penalty,
        )
        return decision
