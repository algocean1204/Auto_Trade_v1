"""F2 AI 분석 -- 종합 보고서 기반으로 매매 판단을 생성한다."""
from __future__ import annotations

import logging

from src.analysis.models import (
    ComprehensiveReport,
    PortfolioState,
    TradingDecision,
)
from src.common.event_bus import EventBus, EventType
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 최소 확신도 -- 이하이면 hold 판단이다
_MIN_CONFIDENCE: float = 0.6

# 최소 포지션 비율이다
_MIN_SIZE_PCT: float = 5.0

# 최대 포지션 비율이다
_MAX_SIZE_PCT: float = 25.0

# 위험 수준별 포지션 스케일링 배수이다
_RISK_SCALE: dict[str, float] = {
    "low": 1.0,
    "medium": 0.7,
    "high": 0.4,
    "critical": 0.0,
}


def _extract_action(report: ComprehensiveReport) -> str:
    """보고서에서 추천 행동을 추출한다."""
    for signal in report.signals:
        action = signal.get("action", "").lower()
        if action in ("buy", "sell"):
            return action
    return "hold"


def _extract_ticker(report: ComprehensiveReport) -> str:
    """보고서에서 추천 티커를 추출한다."""
    for signal in report.signals:
        ticker = signal.get("ticker", "")
        if ticker:
            return ticker.upper()
    return ""


def _extract_direction(report: ComprehensiveReport) -> str:
    """보고서에서 추천 방향을 추출한다."""
    for signal in report.signals:
        direction = signal.get("direction", "bull").lower()
        if direction in ("bull", "bear"):
            return direction
    return "bull"


def _calculate_size(
    report: ComprehensiveReport,
    portfolio: PortfolioState,
) -> float:
    """보고서 확신도와 위험 수준으로 포지션 비율을 산출한다."""
    base = report.confidence * _MAX_SIZE_PCT
    risk_mult = _RISK_SCALE.get(report.risk_level, 0.5)
    adjusted = base * risk_mult
    return round(max(_MIN_SIZE_PCT, min(_MAX_SIZE_PCT, adjusted)), 1)


def _build_reason(report: ComprehensiveReport) -> str:
    """보고서의 추천사항을 요약하여 사유를 생성한다."""
    if report.recommendations:
        return "; ".join(report.recommendations[:3])
    return f"확신도={report.confidence}, 위험={report.risk_level}"


class DecisionMaker:
    """종합 분석 보고서를 기반으로 매매 판단을 생성한다.

    확신도 0.6 미만이면 hold, critical 위험이면 size=0으로 차단한다.
    판단 생성 후 EventBus에 TradingDecision 이벤트를 발행한다.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        logger.info("DecisionMaker 초기화 완료")

    async def decide(
        self,
        report: ComprehensiveReport,
        portfolio: PortfolioState,
    ) -> TradingDecision:
        """종합 보고서와 포트폴리오 상태로 매매 판단을 내린다."""
        decision = self._make_decision(report, portfolio)
        await self._publish(decision)
        logger.info(
            "매매 판단: %s %s (conf=%.2f, size=%.1f%%)",
            decision.action, decision.ticker,
            decision.confidence, decision.size_pct,
        )
        return decision

    def _make_decision(
        self,
        report: ComprehensiveReport,
        portfolio: PortfolioState,
    ) -> TradingDecision:
        """보고서에서 TradingDecision을 생성한다."""
        if report.confidence < _MIN_CONFIDENCE:
            return self._hold_decision(report)

        if report.risk_level == "critical":
            return self._hold_decision(report)

        action = _extract_action(report)
        ticker = _extract_ticker(report)

        if not ticker or action == "hold":
            return self._hold_decision(report)

        return TradingDecision(
            action=action,
            ticker=ticker,
            confidence=report.confidence,
            size_pct=_calculate_size(report, portfolio),
            reason=_build_reason(report),
            direction=_extract_direction(report),
        )

    def _hold_decision(self, report: ComprehensiveReport) -> TradingDecision:
        """hold 판단을 생성한다."""
        return TradingDecision(
            action="hold",
            ticker="",
            confidence=report.confidence,
            size_pct=0.0,
            reason=f"확신도 부족 또는 위험 수준 높음 ({report.risk_level})",
        )

    async def _publish(self, decision: TradingDecision) -> None:
        """EventBus에 매매 판단을 발행한다."""
        try:
            await self._bus.publish(EventType.TRADING_DECISION, decision)
        except Exception:
            logger.exception("TradingDecision 이벤트 발행 실패")
