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
_MAX_TOTAL_EXPOSURE_PCT: float = 80.0


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
        order_price: float = 0.0,
    ) -> SafetyCheckResult:
        """매매 안전성을 검사한다.

        3가지 검사를 순차 실행하며, 실패한 항목을 모두 수집한다.

        Args:
            order_price: 신규 진입 시 매수 예정 단가이다.
                기존 보유종목이 아닌 경우 비중 검사에 필요하다.
                0이면 기존 포지션의 현재가를 사용한다.
        """
        failed: list[str] = []

        # 검사 1: 단일 종목 비중 제한
        reason_1 = self._check_position_concentration(
            ticker, quantity, balance, order_price,
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

        # 검사 4: 전체 포지션 합산 노출도 제한 (80%)
        reason_4 = self._check_total_exposure(
            side, quantity, balance, order_price,
        )
        if reason_4:
            failed.append(reason_4)

        passed = len(failed) == 0
        result = SafetyCheckResult(
            passed=passed,
            checks_run=4,
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
        order_price: float = 0.0,
    ) -> str:
        """단일 종목 비중이 최대치를 초과하는지 검사한다.

        기존 보유종목이 아닌 경우 order_price를 사용하여 정확한
        비중을 계산한다. order_price도 0이면 비중 검사를 건너뛴다.
        """
        if balance.total_equity <= 0:
            return "총 자산이 0 이하이다"

        existing_value = _find_position_value(
            ticker, balance,
        )
        # 기존 보유분 + 신규 주문의 예상 가치
        current_price = _find_current_price(ticker, balance)
        # 신규 종목(기존 보유하지 않은)이면 order_price를 사용한다
        if current_price <= 0:
            current_price = order_price
        if current_price <= 0:
            # 가격 정보가 전혀 없으면 비중 검사를 건너뛴다
            # (가격 미확보 상태에서 차단하면 정상 매매를 막을 수 있다)
            _logger.debug(
                "비중검사 건너뜀: %s 가격 미확보 (order_price=0)",
                ticker,
            )
            return ""
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

    def _check_total_exposure(
        self,
        side: str,
        quantity: int,
        balance: BalanceData,
        order_price: float = 0.0,
    ) -> str:
        """전체 포지션 합산 노출도가 80%를 초과하는지 검사한다.

        기존 모든 포지션의 평가 금액 합계에 신규 주문 금액을 더한 뒤
        총 자산 대비 비율이 _MAX_TOTAL_EXPOSURE_PCT를 초과하면 차단한다.
        """
        if side != "buy":
            return ""
        if balance.total_equity <= 0:
            return ""
        # 기존 포지션 전체의 평가 금액 합산
        total_existing = sum(
            pos.quantity * pos.current_price for pos in balance.positions
        )
        # 신규 주문의 예상 가치를 더한다
        added_value = quantity * order_price if order_price > 0 else 0.0
        total_exposure = total_existing + added_value
        exposure_pct = (total_exposure / balance.total_equity) * 100
        if exposure_pct > _MAX_TOTAL_EXPOSURE_PCT:
            _logger.warning(
                "총노출도초과: %.1f%% > %.1f%% (기존=$%.0f + 신규=$%.0f / 자산=$%.0f)",
                exposure_pct, _MAX_TOTAL_EXPOSURE_PCT,
                total_existing, added_value, balance.total_equity,
            )
            return (
                f"총노출도초과: {exposure_pct:.1f}% "
                f"> {_MAX_TOTAL_EXPOSURE_PCT}%"
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
