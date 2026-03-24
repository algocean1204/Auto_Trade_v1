"""SafetyChecker (F6.2) -- 안전 체인의 두 번째 계층이다.

HardSafety 통과 후 레짐/VIX/거래시간 기반 추가 검증을 수행한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.common.market_clock import get_market_clock
from src.common.ticker_registry import get_ticker_registry
from src.safety.hard_safety.hard_safety import SafetyCheckResult

_logger = get_logger(__name__)

# -- 상수 --
_VIX_EXTREME_THRESHOLD: float = 40.0
_LEVERAGE_3X_THRESHOLD: float = 3.0


class SafetyChecker:
    """안전 체크 체인이다. HardSafety 통과 후 추가 검증한다."""

    def __init__(self) -> None:
        """의존성을 초기화한다."""
        self._registry = get_ticker_registry()
        self._clock = get_market_clock()

    def check(
        self,
        ticker: str,
        regime: str,
        vix: float,
    ) -> SafetyCheckResult:
        """레짐 기반 추가 안전 검사를 실행한다.

        3가지 검사를 순차 실행하며, 실패 항목을 모두 수집한다.
        """
        failed: list[str] = []

        # 검사 1: VIX 극단치에서 모든 신규 매수 차단
        reason_1 = self._check_vix_extreme(vix)
        if reason_1:
            failed.append(reason_1)

        # 검사 2: sideways 레짐에서 3x 레버리지 차단
        reason_2 = self._check_leverage_restriction(
            ticker, regime,
        )
        if reason_2:
            failed.append(reason_2)

        # 검사 3: 거래 시간 외 주문 차단
        reason_3 = self._check_trading_hours()
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
                "SafetyChecker 차단: %s (regime=%s, vix=%.1f) - %s",
                ticker, regime, vix, result.reason,
            )

        return result

    def _check_vix_extreme(self, vix: float) -> str:
        """VIX가 극단치(40 이상)이면 모든 신규 매수를 차단한다."""
        if vix >= _VIX_EXTREME_THRESHOLD:
            return (
                f"VIX극단치: {vix:.1f} >= "
                f"{_VIX_EXTREME_THRESHOLD}"
            )
        return ""

    def _check_leverage_restriction(
        self,
        ticker: str,
        regime: str,
    ) -> str:
        """sideways 레짐에서 3x 레버리지 ETF 매매를 차단한다."""
        if regime != "sideways":
            return ""
        if not self._registry.has_ticker(ticker):
            return ""
        meta = self._registry.get_meta(ticker)
        if abs(meta.leverage) >= _LEVERAGE_3X_THRESHOLD:
            return (
                f"3x레버리지제한: sideways에서 "
                f"{ticker}({meta.leverage}x) 차단"
            )
        return ""

    def _check_trading_hours(self) -> str:
        """거래 시간 외에는 주문을 차단한다."""
        if not self._clock.is_trading_window():
            return "거래시간외: 현재 매매 윈도우가 아니다"
        return ""
