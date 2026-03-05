"""F2 AI 분석 -- 오버나이트 포지션 유지/청산을 판단한다."""
from __future__ import annotations

import logging

from src.analysis.models import MarketRegime, OvernightDecision
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 인버스(Bear) ETF 목록이다 -- 하락장에서 홀딩 우선
_BEAR_ETFS: set[str] = {"SOXS", "NVDS", "SQQQ", "SPXS", "SDOW", "TZA"}

# 하락장 레짐이다 -- Bear ETF 홀딩을 허용한다
_BEARISH_REGIMES: set[str] = {"mild_bear", "crash"}

# 청산 권고 VIX 급등 임계값이다
_VIX_SPIKE_THRESHOLD: float = 5.0


def _is_bear_etf(ticker: str) -> bool:
    """티커가 인버스(Bear) ETF인지 확인한다."""
    return ticker.upper() in _BEAR_ETFS


def _is_bearish_regime(regime: MarketRegime) -> bool:
    """현재 레짐이 하락장인지 확인한다."""
    return regime.regime_type in _BEARISH_REGIMES


def _should_hold_bear_in_downturn(
    ticker: str,
    regime: MarketRegime,
) -> bool:
    """Bear ETF가 하락장에서 홀딩 대상인지 판단한다."""
    return _is_bear_etf(ticker) and _is_bearish_regime(regime)


def _check_vix_spike(market_context: dict) -> bool:
    """VIX 급등 여부를 확인한다."""
    vix_change = market_context.get("vix_change", 0.0)
    return float(vix_change) >= _VIX_SPIKE_THRESHOLD


def _evaluate_position(
    position: dict,
    market_context: dict,
    regime: MarketRegime,
) -> OvernightDecision:
    """개별 포지션의 오버나이트 판단을 수행한다."""
    ticker = position.get("ticker", "UNKNOWN")
    pnl_pct = float(position.get("pnl_pct", 0.0))

    # Bear ETF는 하락장에서 홀딩한다
    if _should_hold_bear_in_downturn(ticker, regime):
        return OvernightDecision(
            ticker=ticker, action="hold",
            reason=f"Bear ETF 하락장 홀딩 ({regime.regime_type})",
        )

    # VIX 급등 시 Bull 포지션 청산한다
    if _check_vix_spike(market_context) and not _is_bear_etf(ticker):
        return OvernightDecision(
            ticker=ticker, action="liquidate",
            reason="VIX 급등으로 Bull 포지션 오버나이트 위험",
        )

    # max_hold_days=0(당일 청산) 레짐에서는 청산한다
    if regime.params.max_hold_days == 0 and not _is_bear_etf(ticker):
        return OvernightDecision(
            ticker=ticker, action="liquidate",
            reason=f"당일 청산 레짐 ({regime.regime_type})",
        )

    # 손실 포지션 + crash 레짐이면 청산한다
    if pnl_pct < -1.0 and regime.regime_type == "crash":
        return OvernightDecision(
            ticker=ticker, action="liquidate",
            reason=f"Crash 레짐 손실 포지션 (PnL={pnl_pct:.1f}%)",
        )

    return OvernightDecision(
        ticker=ticker, action="hold",
        reason=f"홀딩 유지 (PnL={pnl_pct:.1f}%, 레짐={regime.regime_type})",
    )


class OvernightJudge:
    """보유 포지션의 오버나이트 유지/청산을 판단한다.

    핵심: Bear ETF는 하락장(mild_bear/crash)에서 청산 제외한다.
    당일 청산 레짐이면 Bull 포지션은 청산한다.
    """

    def __init__(self) -> None:
        logger.info("OvernightJudge 초기화 완료")

    def judge(
        self,
        positions: list[dict],
        market_context: dict,
        regime: MarketRegime,
    ) -> list[OvernightDecision]:
        """모든 포지션의 오버나이트 판단을 수행한다."""
        decisions: list[OvernightDecision] = []
        for pos in positions:
            decision = _evaluate_position(pos, market_context, regime)
            decisions.append(decision)
            logger.info(
                "오버나이트: %s → %s (%s)",
                decision.ticker, decision.action, decision.reason,
            )
        return decisions
