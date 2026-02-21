"""
청산 전략 모듈

포지션을 모니터링하면서 청산 조건을 감지한다.
우선순위: 손절 > 트레일링 스탑 > 익절 > 보유기간 > EOD > VIX 긴급
"""

from datetime import datetime
from typing import Any

from src.strategy.params import (
    HOLDING_RULES,
    REGIMES,
    StrategyParams,
)
from src.utils.logger import get_logger
from src.utils.market_hours import MarketHours

logger = get_logger(__name__)

# 레짐별 익절 목표 (%)
_REGIME_TAKE_PROFIT: dict[str, float] = {
    "strong_bull": 4.0,
    "mild_bull": 3.0,
    "sideways": 2.0,
    "mild_bear": 2.5,
    "crash": 1.5,
}

# 보유일수별 부분 청산 비율
_HOLDING_LIQUIDATION_RATIO: dict[int, float] = {
    3: 0.50,   # day 3: 50% 부분 청산
    4: 0.75,   # day 4: 75% 부분 청산
    5: 1.00,   # day 5: 100% 강제 청산
}

# VIX 긴급 청산 임계값
_VIX_EMERGENCY_THRESHOLD: float = 35.0


class ExitStrategy:
    """청산 전략 결정 클래스.

    보유 포지션에 대해 다양한 청산 조건을 체크하고,
    조건이 충족되면 청산 지시를 반환한다.
    """

    def __init__(self, params: StrategyParams, market_hours: MarketHours) -> None:
        """ExitStrategy 초기화.

        Args:
            params: 전략 파라미터 관리 인스턴스.
            market_hours: 시장 시간 관리 인스턴스.
        """
        self.params = params
        self.market_hours = market_hours
        self._ticker_params_manager = None

    def set_ticker_params_manager(self, manager: object) -> None:
        """종목별 파라미터 관리자를 주입한다.

        Args:
            manager: TickerParamsManager 인스턴스.
        """
        self._ticker_params_manager = manager
        logger.info("ExitStrategy: TickerParamsManager 주입 완료")

    def check_exit_conditions(
        self,
        position: dict[str, Any],
        current_price: float,
        regime: str,
        vix: float,
    ) -> dict[str, Any] | None:
        """모든 청산 조건을 우선순위에 따라 체크한다.

        체크 순서 (우선순위):
        1. STOP_LOSS (-2%) -> 즉시 전량 청산
        2. TRAILING_STOP (최고점 대비 -1.5%) -> 즉시 전량 청산
        3. VIX 긴급 (VIX > 35) -> 즉시 전량 청산
        4. TAKE_PROFIT (+3%, 레짐별 조정) -> 전량 청산
        5. 보유일수 규칙 (day 3~5 단계적 청산)
        6. EOD 청산 (마감 30분 전)

        Args:
            position: 보유 포지션 정보.
                {
                    "ticker": str,
                    "entry_price": float,
                    "quantity": int,
                    "direction": "bull" | "bear",
                    "entry_at": datetime,
                    "highest_price": float,
                    "hold_days": int,
                }
            current_price: 현재 시장가.
            regime: 현재 시장 레짐.
            vix: 현재 VIX 지수 값.

        Returns:
            청산 지시 딕셔너리 또는 None (청산 조건 미충족).
            {
                "action": "sell",
                "reason": str,
                "quantity": int,
                "urgency": "immediate" | "normal",
                "trigger": str,
            }
        """
        ticker = position.get("ticker", "UNKNOWN")
        entry_price = position.get("entry_price", 0.0)
        quantity = position.get("quantity", 0)

        if entry_price <= 0 or quantity <= 0:
            logger.warning("포지션 데이터 불완전: ticker=%s", ticker)
            return None

        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
        logger.debug(
            "청산 조건 체크: ticker=%s, entry=%.2f, current=%.2f, pnl=%.2f%%, "
            "hold_days=%d, regime=%s, vix=%.1f",
            ticker, entry_price, current_price, pnl_pct,
            position.get("hold_days", 0), regime, vix,
        )

        # 1. 손절 체크 (최우선)
        result = self._check_stop_loss(position, current_price)
        if result is not None:
            return result

        # 2. 트레일링 스탑 체크
        result = self._check_trailing_stop(position, current_price)
        if result is not None:
            return result

        # 3. VIX 긴급 청산 체크
        result = self._check_vix_emergency(vix, position)
        if result is not None:
            return result

        # 4. 익절 체크
        result = self._check_take_profit(position, current_price, regime)
        if result is not None:
            return result

        # 5. 보유 기간 규칙 체크
        result = self._check_holding_period(position)
        if result is not None:
            return result

        # 6. EOD 청산 체크
        result = self._check_eod_close(position)
        if result is not None:
            return result

        return None

    def _check_stop_loss(
        self, position: dict[str, Any], current_price: float
    ) -> dict[str, Any] | None:
        """손절 조건을 체크한다.

        현재 가격이 진입가 대비 STOP_LOSS_PCT 이하로 하락하면
        즉시 전량 청산을 지시한다.

        Args:
            position: 보유 포지션 정보.
            current_price: 현재 시장가.

        Returns:
            청산 지시 또는 None.
        """
        entry_price = position["entry_price"]
        quantity = position["quantity"]
        ticker = position.get("ticker", "UNKNOWN")

        # 종목별 stop_loss_pct 적용 (있으면 종목별, 없으면 글로벌)
        if self._ticker_params_manager is not None:
            stop_loss_pct = self._ticker_params_manager.get_effective_param(
                ticker, "stop_loss_pct"
            )
        else:
            stop_loss_pct = self.params.get_param("stop_loss_pct")  # 음수 (-2.0)

        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0

        if pnl_pct <= stop_loss_pct:
            logger.warning(
                "STOP LOSS 발동: ticker=%s, pnl=%.2f%% <= %.2f%%",
                ticker, pnl_pct, stop_loss_pct,
            )
            return {
                "action": "sell",
                "reason": f"손절: {pnl_pct:.2f}% (임계값: {stop_loss_pct:.1f}%)",
                "quantity": quantity,
                "urgency": "immediate",
                "trigger": "stop_loss",
                "pnl_pct": round(pnl_pct, 2),
            }
        return None

    def _check_trailing_stop(
        self, position: dict[str, Any], current_price: float
    ) -> dict[str, Any] | None:
        """트레일링 스탑 조건을 체크한다.

        보유 기간 중 최고가 대비 TRAILING_STOP_PCT 이상 하락하면
        즉시 전량 청산을 지시한다.

        Args:
            position: 보유 포지션 정보 (highest_price 필수).
            current_price: 현재 시장가.

        Returns:
            청산 지시 또는 None.
        """
        highest_price = position.get("highest_price", 0.0)
        quantity = position["quantity"]
        ticker = position.get("ticker", "UNKNOWN")

        # 종목별 trailing_stop_pct 적용 (있으면 종목별, 없으면 글로벌)
        if self._ticker_params_manager is not None:
            trailing_stop_pct = self._ticker_params_manager.get_effective_param(
                ticker, "trailing_stop_pct"
            )
        else:
            trailing_stop_pct = self.params.get_param("trailing_stop_pct")

        if highest_price <= 0:
            return None

        drop_from_high_pct = ((highest_price - current_price) / highest_price) * 100.0

        if drop_from_high_pct >= trailing_stop_pct:
            logger.warning(
                "TRAILING STOP 발동: ticker=%s, 최고가=%.2f, "
                "현재=%.2f, 하락=%.2f%% >= %.2f%%",
                ticker, highest_price, current_price,
                drop_from_high_pct, trailing_stop_pct,
            )
            return {
                "action": "sell",
                "reason": (
                    f"트레일링 스탑: 최고가 {highest_price:.2f} 대비 "
                    f"-{drop_from_high_pct:.2f}% (임계값: {trailing_stop_pct:.1f}%)"
                ),
                "quantity": quantity,
                "urgency": "immediate",
                "trigger": "trailing_stop",
                "drop_from_high_pct": round(drop_from_high_pct, 2),
            }
        return None

    def _check_take_profit(
        self,
        position: dict[str, Any],
        current_price: float,
        regime: str,
    ) -> dict[str, Any] | None:
        """익절 조건을 체크한다.

        현재 가격이 진입가 대비 레짐별 TAKE_PROFIT 이상 상승하면
        전량 청산을 지시한다.

        Args:
            position: 보유 포지션 정보.
            current_price: 현재 시장가.
            regime: 현재 시장 레짐.

        Returns:
            청산 지시 또는 None.
        """
        entry_price = position["entry_price"]
        quantity = position["quantity"]
        ticker = position.get("ticker", "UNKNOWN")

        # 종목별 take_profit_pct가 있으면 우선 적용, 없으면 레짐별 기본값
        if self._ticker_params_manager is not None:
            ticker_tp = self._ticker_params_manager.get_effective_params(ticker).get("take_profit_pct")
            if ticker_tp is not None:
                take_profit_pct = ticker_tp
            else:
                take_profit_pct = self.get_regime_take_profit(regime)
        else:
            take_profit_pct = self.get_regime_take_profit(regime)

        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0

        if pnl_pct >= take_profit_pct:
            logger.info(
                "TAKE PROFIT 도달: ticker=%s, pnl=%.2f%% >= %.2f%%",
                ticker, pnl_pct, take_profit_pct,
            )
            return {
                "action": "sell",
                "reason": (
                    f"익절: {pnl_pct:.2f}% (목표: {take_profit_pct:.1f}%, "
                    f"regime={regime})"
                ),
                "quantity": quantity,
                "urgency": "normal",
                "trigger": "take_profit",
                "pnl_pct": round(pnl_pct, 2),
            }
        return None

    def _check_holding_period(
        self, position: dict[str, Any]
    ) -> dict[str, Any] | None:
        """보유 기간 규칙에 따른 청산 조건을 체크한다.

        day 3: 50% 부분 청산
        day 4: 75% 부분 청산
        day 5+: 100% 강제 청산

        Args:
            position: 보유 포지션 정보 (hold_days 필수).

        Returns:
            청산 지시 또는 None.
        """
        hold_days = position.get("hold_days", 0)
        quantity = position["quantity"]
        ticker = position.get("ticker", "UNKNOWN")

        if hold_days < 3:
            return None

        # day 5 이상이면 강제 전량 청산
        if hold_days >= 5:
            liquidation_ratio = 1.0
        else:
            liquidation_ratio = _HOLDING_LIQUIDATION_RATIO.get(hold_days, 0.0)

        if liquidation_ratio <= 0:
            return None

        sell_quantity = max(1, int(quantity * liquidation_ratio))
        # 100% 청산 시 정확히 전량
        if liquidation_ratio >= 1.0:
            sell_quantity = quantity

        holding_rule = HOLDING_RULES.get(hold_days, HOLDING_RULES[5])
        urgency = "immediate" if hold_days >= 5 else "normal"

        logger.info(
            "보유기간 규칙 발동: ticker=%s, hold_days=%d, "
            "청산비율=%.0f%%, 수량=%d/%d",
            ticker, hold_days, liquidation_ratio * 100,
            sell_quantity, quantity,
        )
        return {
            "action": "sell",
            "reason": f"보유기간 {hold_days}일: {holding_rule} (청산 {liquidation_ratio:.0%})",
            "quantity": sell_quantity,
            "urgency": urgency,
            "trigger": "holding_period",
            "hold_days": hold_days,
            "liquidation_ratio": liquidation_ratio,
        }

    def _check_eod_close(
        self, position: dict[str, Any]
    ) -> dict[str, Any] | None:
        """장 마감 전(EOD) 청산 조건을 체크한다.

        EOD 청산이 활성화되어 있고 마감 30분 전이면 전량 청산을 지시한다.

        Args:
            position: 보유 포지션 정보.

        Returns:
            청산 지시 또는 None.
        """
        ticker = position.get("ticker", "UNKNOWN")

        # 종목별 eod_close 파라미터 적용 (있으면 종목별, 없으면 글로벌)
        if self._ticker_params_manager is not None:
            eod_close_enabled = self._ticker_params_manager.get_effective_param(
                ticker, "eod_close"
            )
        else:
            eod_close_enabled = self.params.get_param("eod_close")

        if not eod_close_enabled:
            return None

        if not self.market_hours.should_eod_close():
            return None

        quantity = position["quantity"]
        hold_days = position.get("hold_days", 0)

        # 당일 포지션(hold_days=0)에 대해서만 EOD 청산 적용
        # 다일 보유 포지션은 holding_period 규칙으로 관리
        if hold_days > 0:
            logger.debug(
                "종목 %s: 다일 보유 포지션(day %d), EOD 청산 대신 보유기간 규칙 적용",
                ticker, hold_days,
            )
            return None

        logger.info(
            "EOD 청산: ticker=%s, 마감 30분 전 전량 청산",
            ticker,
        )
        return {
            "action": "sell",
            "reason": "장 마감 30분 전 당일 포지션 청산 (EOD)",
            "quantity": quantity,
            "urgency": "normal",
            "trigger": "eod_close",
        }

    def _check_vix_emergency(
        self, vix: float, position: dict[str, Any]
    ) -> dict[str, Any] | None:
        """VIX 긴급 청산 조건을 체크한다.

        VIX가 임계값(35)을 초과하면 즉시 전량 청산을 지시한다.

        Args:
            vix: 현재 VIX 지수 값.
            position: 보유 포지션 정보.

        Returns:
            청산 지시 또는 None.
        """
        vix_threshold = self.params.get_param("vix_shutdown_threshold")

        if vix < vix_threshold:
            return None

        quantity = position["quantity"]
        ticker = position.get("ticker", "UNKNOWN")

        logger.warning(
            "VIX 긴급 청산: ticker=%s, VIX=%.1f >= 임계값 %d, 전량 즉시 청산",
            ticker, vix, vix_threshold,
        )
        return {
            "action": "sell",
            "reason": f"VIX 긴급 청산: VIX {vix:.1f} >= {vix_threshold}",
            "quantity": quantity,
            "urgency": "immediate",
            "trigger": "vix_emergency",
            "vix": vix,
        }

    @staticmethod
    def update_highest_price(
        position: dict[str, Any], current_price: float
    ) -> float:
        """보유 중 최고가를 업데이트한다 (트레일링 스탑 용).

        Args:
            position: 보유 포지션 정보. highest_price 키가 in-place로 업데이트됨.
            current_price: 현재 시장가.

        Returns:
            업데이트된 최고가.
        """
        highest = position.get("highest_price", 0.0)
        if current_price > highest:
            position["highest_price"] = current_price
            logger.debug(
                "종목 %s: 최고가 업데이트 %.2f -> %.2f",
                position.get("ticker", "UNKNOWN"), highest, current_price,
            )
            return current_price
        return highest

    def get_regime_take_profit(self, regime: str) -> float:
        """레짐별 익절 목표를 반환한다.

        Args:
            regime: 시장 레짐 이름.

        Returns:
            익절 목표 퍼센트. 매칭 레짐이 없으면 기본 TAKE_PROFIT_PCT 사용.
        """
        regime_tp = _REGIME_TAKE_PROFIT.get(regime)
        if regime_tp is not None:
            return regime_tp

        # REGIMES 테이블에서 take_profit 조회
        regime_config = REGIMES.get(regime, {})
        if "take_profit" in regime_config:
            return regime_config["take_profit"]

        return self.params.get_param("take_profit_pct")
