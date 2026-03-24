"""F2 AI 분석 -- VIX 기반 시장 레짐을 판별한다."""
from __future__ import annotations

import logging

from src.analysis.models import MarketRegime, RegimeParams
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# VIX 구간별 레짐 정의이다
# (상한_exclusive, regime_type, RegimeParams)
_REGIME_TABLE: list[tuple[float, str, RegimeParams]] = [
    (
        15.0, "strong_bull",
        RegimeParams(
            take_profit=0.0, trailing_stop=4.0, max_hold_days=0,
            position_multiplier=1.0, allow_bull_entry=True,
            allow_bear_entry=False, prefer_inverse=False,
        ),
    ),
    (
        20.0, "mild_bull",
        RegimeParams(
            take_profit=3.0, trailing_stop=2.5, max_hold_days=2,
            position_multiplier=1.0, allow_bull_entry=True,
            allow_bear_entry=False, prefer_inverse=False,
        ),
    ),
    (
        25.0, "sideways",
        RegimeParams(
            take_profit=2.0, trailing_stop=1.5, max_hold_days=0,
            position_multiplier=0.7, allow_bull_entry=True,
            allow_bear_entry=True, prefer_inverse=False,
        ),
    ),
    (
        35.0, "mild_bear",
        RegimeParams(
            take_profit=2.5, trailing_stop=2.0, max_hold_days=1,
            position_multiplier=0.5, allow_bull_entry=False,
            allow_bear_entry=True, prefer_inverse=True,
        ),
    ),
]

# VIX 35 이상이면 crash 레짐이다
_CRASH_PARAMS: RegimeParams = RegimeParams(
    take_profit=5.0, trailing_stop=3.0, max_hold_days=0,
    position_multiplier=0.8, allow_bull_entry=False,
    allow_bear_entry=True, prefer_inverse=True,
)


def _find_regime(vix: float) -> tuple[str, RegimeParams]:
    """VIX 값에 맞는 레짐과 파라미터를 찾아 반환한다."""
    for upper_bound, regime_type, params in _REGIME_TABLE:
        if vix < upper_bound:
            return regime_type, params
    return "crash", _CRASH_PARAMS


class RegimeDetector:
    """VIX 수치 기반으로 시장 레짐을 판별한다.

    5단계 레짐: strong_bull / mild_bull / sideways / mild_bear / crash.
    take_profit=0은 무제한(트레일링만), max_hold_days=0은 당일 청산이다.
    히스테리시스 밴드(0.5)를 적용하여 경계값 부근에서의 레짐 진동을 방지한다.
    """

    # VIX 경계값 근처에서 레짐 전환 시 최소 변동폭이다
    _HYSTERESIS_BAND: float = 0.5

    def __init__(self) -> None:
        self._prev_regime: str | None = None
        self._prev_vix: float | None = None
        logger.info("RegimeDetector 초기화 완료 (히스테리시스=%.1f)", self._HYSTERESIS_BAND)

    def detect(self, vix_value: float) -> MarketRegime:
        """VIX 값으로 현재 시장 레짐을 판별하여 반환한다.

        이전 레짐이 존재하면 히스테리시스 밴드를 적용하여
        VIX가 경계를 0.5 이상 넘어야만 레짐을 전환한다.
        """
        clamped = max(0.0, vix_value)
        new_regime_type, new_params = _find_regime(clamped)

        # 히스테리시스 적용: 이전 레짐이 있고 레짐이 변경되려 할 때
        if (
            self._prev_regime is not None
            and new_regime_type != self._prev_regime
        ):
            # 모든 경계값에 대해 히스테리시스 밴드 확인한다
            crossed_by_enough = True
            for upper_bound, _regime_type, _params in _REGIME_TABLE:
                # VIX가 경계 근처(±히스테리시스 밴드 이내)에 있으면 전환하지 않는다
                if abs(clamped - upper_bound) < self._HYSTERESIS_BAND:
                    crossed_by_enough = False
                    break

            if not crossed_by_enough:
                # 경계를 충분히 넘지 못했으므로 이전 레짐을 유지한다
                prev_type, prev_params = _find_regime(self._prev_vix or clamped)
                logger.debug(
                    "히스테리시스 적용: VIX=%.2f 경계 근처 — %s 유지 (전환 시도: %s)",
                    clamped, self._prev_regime, new_regime_type,
                )
                regime_type = prev_type
                params = prev_params
            else:
                regime_type = new_regime_type
                params = new_params
        else:
            regime_type = new_regime_type
            params = new_params

        self._prev_regime = regime_type
        self._prev_vix = clamped

        logger.info(
            "레짐 판별: VIX=%.2f → %s (TP=%.1f%%, TS=%.1f%%)",
            clamped, regime_type, params.take_profit, params.trailing_stop,
        )
        return MarketRegime(
            regime_type=regime_type,
            vix=clamped,
            params=params,
        )
