"""HardSafety (F6.1) -- 최상위 안전 계층이다. 모든 매매 전 최종 검증한다.

단일 종목 비중, 레짐 기반 매수 차단, 동시 포지션 수 제한을 검사한다.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.common.broker_gateway import BalanceData
from src.common.logger import get_logger
from src.common.ticker_registry import get_ticker_registry
from src.strategy.params.strategy_params import StrategyParamsManager

_logger = get_logger(__name__)

# -- 상수 --
_BEAR_REGIMES: frozenset[str] = frozenset({"crash", "mild_bear"})
_MAX_CONCURRENT_POSITIONS: int = 10


class SafetyCheckResult(BaseModel):
    """안전 검사 결과이다."""

    passed: bool
    checks_run: int
    failed_checks: list[str] = []
    reason: str = ""


class HardSafety:
    """최상위 안전 장치이다. 모든 매매 전 반드시 통과해야 한다."""

    def __init__(self, max_position_pct: float | None = None) -> None:
        """초기화한다.

        Args:
            max_position_pct: 단일 종목 최대 비중(%). None이면
                strategy_params.json에서 로드한다.
        """
        if max_position_pct is not None:
            self._max_position_pct = max_position_pct
        else:
            # strategy_params.json의 max_position_pct를 기준으로 사용한다
            params = StrategyParamsManager().load()
            self._max_position_pct = params.max_position_pct
            _logger.info(
                "HardSafety max_position_pct=%.2f%% (strategy_params.json)",
                self._max_position_pct,
            )
        self._registry = get_ticker_registry()

    def check(
        self,
        ticker: str,
        side: str,
        quantity: int,
        balance: BalanceData,
        regime: str,
    ) -> SafetyCheckResult:
        """매매 안전성을 검사한다.

        3가지 검사를 순차 실행하며, 실패한 항목을 모두 수집한다.
        """
        failed: list[str] = []

        # 검사 1: 단일 종목 비중 제한
        reason_1 = self._check_position_concentration(
            ticker, quantity, balance,
        )
        if reason_1:
            failed.append(reason_1)

        # 검사 2: 하락장 bull ETF 매수 차단
        reason_2 = self._check_regime_restriction(
            ticker, side, regime,
        )
        if reason_2:
            failed.append(reason_2)

        # 검사 3: 동시 포지션 수 제한
        reason_3 = self._check_max_positions(side, balance)
        if reason_3:
            failed.append(reason_3)

        passed = len(failed) == 0
        result = SafetyCheckResult(
            passed=passed,
            checks_run=3,
            failed_checks=failed,
            reason="; ".join(failed) if failed else "",
        )

        if not passed:
            _logger.warning(
                "HardSafety 차단: %s %s %d주 - %s",
                side, ticker, quantity, result.reason,
            )

        return result

    def _check_position_concentration(
        self,
        ticker: str,
        quantity: int,
        balance: BalanceData,
    ) -> str:
        """단일 종목 비중이 최대치를 초과하는지 검사한다."""
        if balance.total_equity <= 0:
            return "총 자산이 0 이하이다"

        existing_value = _find_position_value(
            ticker, balance,
        )
        # 기존 보유분 + 신규 주문의 예상 가치
        current_price = _find_current_price(ticker, balance)
        added_value = quantity * current_price
        total_value = existing_value + added_value

        pct = (total_value / balance.total_equity) * 100
        if pct > self._max_position_pct:
            return (
                f"단일종목비중초과: {ticker} "
                f"{pct:.1f}% > {self._max_position_pct}%"
            )
        return ""

    def _check_regime_restriction(
        self,
        ticker: str,
        side: str,
        regime: str,
    ) -> str:
        """하락장 레짐에서 bull ETF 매수를 차단한다."""
        if side != "buy":
            return ""
        if regime not in _BEAR_REGIMES:
            return ""
        # 인버스(bear) ETF는 하락장에서 매수 허용
        if self._registry.has_ticker(ticker):
            if self._registry.is_inverse(ticker):
                return ""
        return f"레짐제한: {regime}에서 bull ETF({ticker}) 매수 차단"

    def _check_max_positions(
        self,
        side: str,
        balance: BalanceData,
    ) -> str:
        """동시 보유 포지션 수가 한도를 초과하는지 검사한다."""
        if side != "buy":
            return ""
        current_count = len(balance.positions)
        if current_count >= _MAX_CONCURRENT_POSITIONS:
            return (
                f"포지션수초과: {current_count}개 "
                f">= {_MAX_CONCURRENT_POSITIONS}개"
            )
        return ""


def _find_position_value(ticker: str, balance: BalanceData) -> float:
    """기존 보유 포지션의 평가 금액을 반환한다."""
    for pos in balance.positions:
        if pos.ticker == ticker:
            return pos.quantity * pos.current_price
    return 0.0


def _find_current_price(ticker: str, balance: BalanceData) -> float:
    """보유 포지션에서 현재가를 조회한다. 없으면 0.0이다."""
    for pos in balance.positions:
        if pos.ticker == ticker:
            return pos.current_price
    return 0.0
