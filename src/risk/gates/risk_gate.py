"""RiskGate (F6.5) -- 7개 리스크 게이트를 순차 실행한다.

각 게이트는 특정 리스크 지표를 평가하여 매매 진입을 허용/차단한다.
EntryStrategy가 실제 진입 판단에 사용하는 것과 별개로,
이 클래스는 대시보드 표시용 종합 리스크 상태를 제공한다.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 게이트 이름 상수 --
_GATE_NAMES: list[str] = [
    "OBI 확인",
    "교차자산 모멘텀",
    "고래 활동",
    "마이크로 레짐",
    "섹터 상관관계",
    "틸트 감지",
    "마찰 비용",
]

# 각 게이트 임계값이다
_OBI_THRESHOLD: float = 0.3
_CROSS_ASSET_THRESHOLD: float = 0.3
_WHALE_THRESHOLD: float = 0.3
_FRICTION_MAX_BPS: float = 30.0  # 스프레드+슬리피지 합계 최대 30bps


class GateDetail(BaseModel):
    """개별 게이트 결과이다."""

    gate_name: str
    passed: bool
    score: float
    reason: str = ""


class RiskGateResult(BaseModel):
    """리스크 게이트 종합 결과이다."""

    all_passed: bool
    gates: list[GateDetail]
    blocked_by: str | None = None


class RiskGate:
    """7개 리스크 게이트이다.

    매매 진입 전 7가지 리스크 지표를 순차 평가한다.
    하나라도 실패하면 진입을 차단한다.
    """

    def __init__(self) -> None:
        """게이트 평가기를 초기화한다."""
        # 게이트별 평가 함수 목록이다
        self._evaluators = [
            self._gate_obi,
            self._gate_cross_asset,
            self._gate_whale,
            self._gate_micro_regime,
            self._gate_sector_correlation,
            self._gate_tilt,
            self._gate_friction,
        ]

    def evaluate(
        self,
        ticker: str,
        side: str,
        indicators: dict,
    ) -> RiskGateResult:
        """7개 게이트를 순차 평가한다.

        하나라도 실패하면 차단하되, 모든 게이트를 실행하여
        실패 목록을 전부 수집한다.
        """
        gates: list[GateDetail] = []
        blocked_by: str | None = None

        for i, evaluator in enumerate(self._evaluators):
            gate_name = _GATE_NAMES[i]
            detail = evaluator(
                ticker, side, indicators, gate_name,
            )
            gates.append(detail)
            if not detail.passed and blocked_by is None:
                blocked_by = gate_name

        all_passed = all(g.passed for g in gates)

        if not all_passed:
            _logger.info(
                "RiskGate 차단: %s %s -> %s",
                side, ticker, blocked_by,
            )

        return RiskGateResult(
            all_passed=all_passed,
            gates=gates,
            blocked_by=blocked_by,
        )

    def _gate_obi(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 1: OBI(Order Book Imbalance) 확인한다."""
        obi = indicators.get("obi", 0.0)
        if obi == 0.0:
            return GateDetail(
                gate_name=name, passed=True,
                score=0.0, reason="데이터 미가용 (통과)",
            )
        passed = obi > _OBI_THRESHOLD
        return GateDetail(
            gate_name=name, passed=passed,
            score=obi,
            reason="" if passed else f"OBI {obi:.3f} < {_OBI_THRESHOLD}",
        )

    def _gate_cross_asset(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 2: 교차자산 모멘텀을 확인한다."""
        score = indicators.get("cross_asset_score", 0.0)
        if score == 0.0:
            return GateDetail(
                gate_name=name, passed=True,
                score=0.0, reason="데이터 미가용 (통과)",
            )
        passed = score > _CROSS_ASSET_THRESHOLD
        return GateDetail(
            gate_name=name, passed=passed,
            score=score,
            reason="" if passed else f"정렬도 {score:.3f} < {_CROSS_ASSET_THRESHOLD}",
        )

    def _gate_whale(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 3: 고래 활동을 확인한다."""
        score = indicators.get("whale_score", 0.0)
        if score == 0.0:
            return GateDetail(
                gate_name=name, passed=True,
                score=0.0, reason="데이터 미가용 (통과)",
            )
        passed = score > _WHALE_THRESHOLD
        return GateDetail(
            gate_name=name, passed=passed,
            score=score,
            reason="" if passed else f"고래 점수 {score:.3f} < {_WHALE_THRESHOLD}",
        )

    def _gate_micro_regime(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 4: 마이크로 레짐을 확인한다. trending/mean_reverting만 통과한다."""
        regime = indicators.get("micro_regime", "")
        if not regime:
            return GateDetail(
                gate_name=name, passed=True,
                score=0.0, reason="데이터 미가용 (통과)",
            )
        passed = regime in ("trending", "mean_reverting")
        return GateDetail(
            gate_name=name, passed=passed,
            score=1.0 if passed else 0.0,
            reason="" if passed else f"레짐 {regime}은 진입 부적합",
        )

    def _gate_sector_correlation(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 5: 섹터 상관관계를 확인한다. 회피 섹터면 차단한다."""
        avoid_sectors = indicators.get("avoid_sectors", set())
        ticker_sector = indicators.get("ticker_sector", "")
        if not avoid_sectors or not ticker_sector:
            return GateDetail(
                gate_name=name, passed=True,
                score=0.0, reason="데이터 미가용 (통과)",
            )
        passed = ticker_sector not in avoid_sectors
        return GateDetail(
            gate_name=name, passed=passed,
            score=0.0 if passed else 1.0,
            reason="" if passed else f"섹터 {ticker_sector} 회피 대상",
        )

    def _gate_tilt(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 6: 틸트(감정적 매매) 감지를 확인한다."""
        is_tilted = indicators.get("is_tilted", False)
        passed = not is_tilted
        return GateDetail(
            gate_name=name, passed=passed,
            score=0.0 if passed else 1.0,
            reason="" if passed else "틸트 상태 감지됨",
        )

    def _gate_friction(
        self, ticker: str, side: str,
        indicators: dict, name: str,
    ) -> GateDetail:
        """Gate 7: 마찰 비용(스프레드+슬리피지)을 확인한다."""
        friction = indicators.get("friction_cost", 0.0)
        if friction == 0.0:
            return GateDetail(
                gate_name=name, passed=True,
                score=0.0, reason="데이터 미가용 (통과)",
            )
        passed = friction <= _FRICTION_MAX_BPS
        return GateDetail(
            gate_name=name, passed=passed,
            score=friction,
            reason="" if passed else f"마찰 {friction:.1f}bps > {_FRICTION_MAX_BPS}bps",
        )
