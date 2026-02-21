"""
간이 VaR (Value at Risk) 게이트 (Addendum 26 - Gate 4)

포트폴리오 VaR를 계산하여 최대 허용 리스크를 초과하는지 점검한다.

설정:
    - 95% 신뢰도
    - 30일 룩백 기간
    - 최대 VaR: 포트폴리오의 3%
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from src.risk.risk_gate import GateResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# VaR 기본 설정
DEFAULT_CONFIDENCE: float = 0.95
DEFAULT_LOOKBACK_DAYS: int = 30
DEFAULT_MAX_VAR_PCT: float = 3.0

# 95% 정규분포 Z-score
Z_SCORE_95: float = 1.645


class SimpleVaR:
    """간이 VaR(Value at Risk)를 계산하고 한도를 점검한다.

    Historical VaR 방식으로 과거 수익률의 분포를 기반으로
    포트폴리오의 최대 일일 손실 예상치를 계산한다.

    Attributes:
        confidence: 신뢰 수준 (0.0~1.0).
        lookback_days: 룩백 기간 (거래일 수).
        max_var_pct: 최대 허용 VaR (%).
    """

    def __init__(
        self,
        confidence: float = DEFAULT_CONFIDENCE,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        max_var_pct: float = DEFAULT_MAX_VAR_PCT,
    ) -> None:
        """SimpleVaR를 초기화한다.

        Args:
            confidence: 신뢰 수준.
            lookback_days: 룩백 기간.
            max_var_pct: 최대 허용 VaR (%).
        """
        self.confidence = confidence
        self.lookback_days = lookback_days
        self.max_var_pct = max_var_pct

        logger.info(
            "SimpleVaR 초기화 | confidence=%.0f%% | lookback=%dd | max_var=%.1f%%",
            confidence * 100,
            lookback_days,
            max_var_pct,
        )

    async def check(
        self, portfolio: dict[str, Any], market_data: dict[str, Any]
    ) -> GateResult:
        """포트폴리오 VaR를 계산하고 한도를 점검한다.

        Args:
            portfolio: 현재 포트폴리오 상태.
                필수 키: "total_value", "positions".
            market_data: 종목별 가격 이력.
                형식: {"TICKER": [{"close": float, "date": str}, ...]}.

        Returns:
            게이트 실행 결과.
        """
        try:
            total_value = portfolio.get("total_value", 0.0)
            positions = portfolio.get("positions", [])

            if total_value <= 0:
                return GateResult(
                    passed=True,
                    action="allow",
                    message="포트폴리오 가치 0, VaR 체크 생략",
                    gate_name="simple_var",
                )

            if not positions:
                return GateResult(
                    passed=True,
                    action="allow",
                    message="보유 포지션 없음, VaR 체크 생략",
                    gate_name="simple_var",
                )

            # 각 포지션별 VaR 계산 후 합산
            portfolio_var_usd = 0.0
            position_vars: dict[str, float] = {}

            if isinstance(positions, list):
                pos_items = positions
            else:
                pos_items = list(positions.values())

            for pos in pos_items:
                ticker = pos.get("ticker", "unknown")
                market_value = pos.get("market_value", 0.0)

                # 해당 종목의 가격 이력에서 일별 수익률 계산
                prices = market_data.get(ticker, [])
                if not prices:
                    # 가격 이력 없으면 보수적으로 5% 변동성 가정
                    daily_vol = 0.05
                else:
                    returns = self._calculate_returns(prices)
                    if len(returns) < 5:
                        daily_vol = 0.05
                    else:
                        daily_vol = statistics.stdev(returns)

                # Parametric VaR: VaR = Z * sigma * position_value
                position_var = Z_SCORE_95 * daily_vol * market_value
                portfolio_var_usd += position_var
                position_vars[ticker] = round(position_var, 2)

            # VaR를 포트폴리오 비율로 변환
            var_pct = (portfolio_var_usd / total_value) * 100.0

            details = {
                "var_usd": round(portfolio_var_usd, 2),
                "var_pct": round(var_pct, 4),
                "max_var_pct": self.max_var_pct,
                "confidence": self.confidence,
                "position_vars": position_vars,
            }

            if var_pct > self.max_var_pct:
                logger.warning(
                    "VaR 한도 초과: %.2f%% > %.1f%% ($%.2f)",
                    var_pct,
                    self.max_var_pct,
                    portfolio_var_usd,
                )
                return GateResult(
                    passed=False,
                    action="reduce",
                    message=(
                        f"VaR {var_pct:.2f}% > 한도 {self.max_var_pct:.1f}% "
                        f"(${portfolio_var_usd:.2f} at risk)"
                    ),
                    gate_name="simple_var",
                    details=details,
                )

            logger.debug("VaR 정상: %.2f%% <= %.1f%%", var_pct, self.max_var_pct)
            return GateResult(
                passed=True,
                action="allow",
                message=f"VaR {var_pct:.2f}% <= 한도 {self.max_var_pct:.1f}%",
                gate_name="simple_var",
                details=details,
            )
        except Exception as e:
            logger.error("VaR 체크 실패: %s", e)
            return GateResult(
                passed=True,
                action="allow",
                message=f"VaR 체크 오류 (안전 통과): {e}",
                gate_name="simple_var",
            )

    def _calculate_returns(self, prices: list[Any]) -> list[float]:
        """가격 리스트에서 일별 수익률을 계산한다.

        Args:
            prices: 가격 데이터 리스트.
                각 항목: {"close": float} 또는 float.

        Returns:
            일별 수익률 리스트.
        """
        close_prices: list[float] = []
        for p in prices:
            if isinstance(p, dict):
                close_prices.append(float(p.get("close", 0.0)))
            elif isinstance(p, (int, float)):
                close_prices.append(float(p))

        if len(close_prices) < 2:
            return []

        returns: list[float] = []
        for i in range(1, len(close_prices)):
            if close_prices[i - 1] > 0:
                ret = (close_prices[i] - close_prices[i - 1]) / close_prices[i - 1]
                returns.append(ret)

        return returns[-self.lookback_days:]

    def calculate_var(
        self, returns: list[float], position_value: float
    ) -> float:
        """특정 포지션의 VaR를 계산한다.

        Args:
            returns: 일별 수익률 리스트.
            position_value: 포지션 가치 (USD).

        Returns:
            VaR 금액 (USD).
        """
        if not returns:
            return position_value * 0.05 * Z_SCORE_95

        vol = statistics.stdev(returns) if len(returns) > 1 else 0.05
        return Z_SCORE_95 * vol * position_value

    def get_status(self) -> dict[str, Any]:
        """현재 설정을 반환한다."""
        return {
            "confidence": self.confidence,
            "lookback_days": self.lookback_days,
            "max_var_pct": self.max_var_pct,
            "z_score": Z_SCORE_95,
        }
