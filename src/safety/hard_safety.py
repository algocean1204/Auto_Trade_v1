"""
3중 안전망 중 3차: 하드 세이프티
시스템이 어떤 판단을 하든 이 규칙은 절대 위반할 수 없음.

주요 규칙:
    - 종목당 최대 포지션 15%
    - 전체 포지션 합계 최대 80%
    - 일일 최대 거래 30건
    - 일일 손실 -5% -> 전체 매매 중단
    - 단일 손절 -2%
    - 보유 5일 초과 -> 강제 청산
    - VIX > 35 -> 신규 매수 전면 중단
"""

from typing import Any, Optional

from src.strategy.params import (
    MAX_DAILY_LOSS_PCT,
    MAX_DAILY_TRADES,
    MAX_HOLD_DAYS,
    MAX_POSITION_PCT,
    MAX_TOTAL_POSITION_PCT,
    STOP_LOSS_PCT,
    VIX_SHUTDOWN_THRESHOLD,
    StrategyParams,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SafetyViolationError(Exception):
    """안전 규칙 위반 에러.

    HardSafety에서 정의한 절대 불가침 규칙이 위반되었을 때 발생한다.
    """

    pass


class HardSafety:
    """하드 세이프티: 절대 위반 불가 규칙을 적용한다.

    어떤 AI 판단이나 전략 결정도 이 규칙을 넘어설 수 없다.
    매매 주문 전, 포지션 점검 시 반드시 이 클래스를 통해 검증해야 한다.

    Attributes:
        max_position_pct: 종목당 최대 포지션 비율.
        max_total_position_pct: 전체 포지션 합계 최대 비율.
        max_daily_trades: 일일 최대 거래 횟수.
        max_daily_loss_pct: 일일 최대 손실률 (음수).
        stop_loss_pct: 단일 종목 손절 기준 (음수).
        max_hold_days: 최대 보유 일수.
        vix_shutdown_threshold: VIX 매매 중단 임계값.
        daily_trades: 금일 거래 횟수.
        daily_pnl_pct: 금일 누적 손익률.
        is_shutdown: 일일 손실 한도 도달 여부.
    """

    def __init__(self, params: Optional[StrategyParams] = None) -> None:
        """HardSafety를 초기화한다.

        Args:
            params: StrategyParams 인스턴스. None이면 모듈 상수 기본값 사용.
        """
        if params is not None:
            self.max_position_pct: float = params.get_param("max_position_pct")
            self.max_total_position_pct: float = params.get_param("max_total_position_pct")
            self.max_daily_trades: int = params.get_param("max_daily_trades")
            self.max_daily_loss_pct: float = params.get_param("max_daily_loss_pct")
            self.stop_loss_pct: float = params.get_param("stop_loss_pct")
            self.max_hold_days: int = params.get_param("max_hold_days")
            self.vix_shutdown_threshold: int = params.get_param("vix_shutdown_threshold")
        else:
            self.max_position_pct = MAX_POSITION_PCT          # 15.0
            self.max_total_position_pct = MAX_TOTAL_POSITION_PCT  # 80.0
            self.max_daily_trades = MAX_DAILY_TRADES           # 30
            self.max_daily_loss_pct = MAX_DAILY_LOSS_PCT       # -5.0
            self.stop_loss_pct = STOP_LOSS_PCT                 # -2.0
            self.max_hold_days = MAX_HOLD_DAYS                 # 5
            self.vix_shutdown_threshold = VIX_SHUTDOWN_THRESHOLD  # 35

        # 일일 추적
        self.daily_trades: int = 0
        self.daily_pnl_pct: float = 0.0
        self.is_shutdown: bool = False

        logger.info(
            "HardSafety 초기화 | max_pos=%.1f%% | max_total=%.1f%% | "
            "max_trades=%d | max_loss=%.1f%% | stop_loss=%.1f%% | "
            "max_hold=%dd | vix_shutdown=%d",
            self.max_position_pct,
            self.max_total_position_pct,
            self.max_daily_trades,
            self.max_daily_loss_pct,
            self.stop_loss_pct,
            self.max_hold_days,
            self.vix_shutdown_threshold,
        )

    def check_new_order(
        self, order: dict[str, Any], portfolio: dict[str, Any]
    ) -> tuple[bool, str]:
        """신규 주문을 하드 세이프티 규칙으로 검증한다.

        Args:
            order: 주문 정보 딕셔너리.
                필수 키: "ticker", "side", "quantity", "price".
                side: "buy" 또는 "sell".
            portfolio: 포트폴리오 정보 딕셔너리.
                필수 키: "positions" (리스트), "cash" (float), "total_value" (float).
                각 position: {"ticker", "quantity", "current_price", "avg_price", "market_value"}.

        Returns:
            (allowed, reason) 튜플.
            allowed가 True이면 주문 허용, False이면 거부와 사유.
        """
        # 1. Shutdown 상태 확인
        if self.is_shutdown:
            reason = "일일 손실 한도 도달로 매매 중단 상태"
            logger.warning("주문 거부 [shutdown] | ticker=%s | %s", order.get("ticker"), reason)
            return False, reason

        # 2. 매도 주문은 항상 허용 (청산은 언제나 가능)
        side = order.get("side", "").lower()
        if side == "sell":
            return True, "매도 주문 허용"

        # 3. 일일 거래 횟수 확인
        if self.daily_trades >= self.max_daily_trades:
            reason = f"일일 최대 거래 횟수 초과 ({self.daily_trades}/{self.max_daily_trades})"
            logger.warning("주문 거부 [daily_trades] | ticker=%s | %s", order.get("ticker"), reason)
            return False, reason

        # 4. 종목당 포지션 비율 확인
        total_value = portfolio.get("total_value", 0.0)
        if total_value <= 0:
            reason = "포트폴리오 총 가치가 0 이하"
            logger.warning("주문 거부 [portfolio_value] | %s", reason)
            return False, reason

        ticker = order.get("ticker", "")
        order_value = order.get("quantity", 0) * order.get("price", 0.0)

        # 기존 포지션 가치 계산
        existing_position_value = 0.0
        for pos in portfolio.get("positions", []):
            if pos.get("ticker") == ticker:
                existing_position_value = pos.get("market_value", 0.0)
                break

        new_position_value = existing_position_value + order_value
        position_pct = (new_position_value / total_value) * 100.0

        if position_pct > self.max_position_pct:
            reason = (
                f"종목 {ticker} 포지션 비율 초과: "
                f"{position_pct:.1f}% > {self.max_position_pct:.1f}%"
            )
            logger.warning("주문 거부 [position_limit] | %s", reason)
            return False, reason

        # 5. 전체 포지션 비율 확인
        total_position_value = sum(
            pos.get("market_value", 0.0) for pos in portfolio.get("positions", [])
        )
        new_total_position_value = total_position_value + order_value
        total_position_pct = (new_total_position_value / total_value) * 100.0

        if total_position_pct > self.max_total_position_pct:
            reason = (
                f"전체 포지션 비율 초과: "
                f"{total_position_pct:.1f}% > {self.max_total_position_pct:.1f}%"
            )
            logger.warning("주문 거부 [total_position_limit] | %s", reason)
            return False, reason

        logger.debug(
            "주문 통과 | ticker=%s | pos=%.1f%% | total_pos=%.1f%%",
            ticker,
            position_pct,
            total_position_pct,
        )
        return True, "통과"

    def check_position(self, position: dict[str, Any]) -> Optional[dict[str, Any]]:
        """포지션 안전 체크를 수행한다.

        손절 기준, 보유 기간 기준을 확인하고 필요 시 청산 지시를 반환한다.

        Args:
            position: 포지션 정보 딕셔너리.
                필수 키: "ticker", "quantity", "avg_price", "current_price", "days_held".

        Returns:
            청산이 필요하면 지시 딕셔너리, 아니면 None.
            지시 형식: {"ticker", "action", "quantity", "reason"}.
        """
        ticker = position.get("ticker", "unknown")
        quantity = position.get("quantity", 0)
        avg_price = position.get("avg_price", 0.0)
        current_price = position.get("current_price", 0.0)
        days_held = position.get("days_held", 0)

        # 손익률 계산
        if avg_price > 0:
            pnl_pct = ((current_price - avg_price) / avg_price) * 100.0
        else:
            pnl_pct = 0.0

        # 1. 손절 확인: 손익 <= stop_loss_pct -> 즉시 전량 손절
        if pnl_pct <= self.stop_loss_pct:
            reason = f"손절 기준 도달: {pnl_pct:.2f}% <= {self.stop_loss_pct:.1f}%"
            logger.warning(
                "강제 손절 | ticker=%s | pnl=%.2f%% | qty=%d",
                ticker, pnl_pct, quantity,
            )
            return {
                "ticker": ticker,
                "action": "force_sell",
                "quantity": quantity,
                "reason": reason,
            }

        # 2. 보유 기간 >= max_hold_days -> 즉시 100% 청산
        if days_held >= self.max_hold_days:
            reason = f"최대 보유 기간 도달: {days_held}일 >= {self.max_hold_days}일"
            logger.warning(
                "강제 청산 [max_hold] | ticker=%s | days=%d | qty=%d",
                ticker, days_held, quantity,
            )
            return {
                "ticker": ticker,
                "action": "force_sell",
                "quantity": quantity,
                "reason": reason,
            }

        # 3. 보유 4일 -> 75% 부분 청산
        if days_held == 4:
            sell_qty = int(quantity * 0.75)
            if sell_qty > 0:
                reason = f"보유 4일차 75% 부분 청산 (pnl={pnl_pct:.2f}%)"
                logger.warning(
                    "부분 청산 [day4] | ticker=%s | sell_qty=%d / %d",
                    ticker, sell_qty, quantity,
                )
                return {
                    "ticker": ticker,
                    "action": "partial_sell",
                    "quantity": sell_qty,
                    "reason": reason,
                }

        # 4. 보유 3일 -> 50% 부분 청산
        if days_held == 3:
            sell_qty = int(quantity * 0.50)
            if sell_qty > 0:
                reason = f"보유 3일차 50% 부분 청산 (pnl={pnl_pct:.2f}%)"
                logger.warning(
                    "부분 청산 [day3] | ticker=%s | sell_qty=%d / %d",
                    ticker, sell_qty, quantity,
                )
                return {
                    "ticker": ticker,
                    "action": "partial_sell",
                    "quantity": sell_qty,
                    "reason": reason,
                }

        return None

    def update_daily_pnl(self, pnl_pct: float) -> None:
        """일일 누적 손익률을 업데이트한다.

        -5% 이하 도달 시 is_shutdown을 True로 설정하여 모든 신규 매매를 중단한다.

        Args:
            pnl_pct: 현재 일일 누적 손익률 (음수=손실).
        """
        self.daily_pnl_pct = pnl_pct
        logger.info("일일 손익 업데이트 | pnl=%.2f%%", pnl_pct)

        if pnl_pct <= self.max_daily_loss_pct:
            self.is_shutdown = True
            logger.critical(
                "일일 손실 한도 도달! | pnl=%.2f%% <= %.1f%% | 모든 매매 중단",
                pnl_pct,
                self.max_daily_loss_pct,
            )

    def record_trade(self) -> None:
        """거래 카운트를 1 증가시킨다."""
        self.daily_trades += 1
        logger.debug(
            "거래 기록 | daily_trades=%d/%d",
            self.daily_trades,
            self.max_daily_trades,
        )

    def reset_daily(self) -> None:
        """일일 카운터를 리셋한다. 매일 자정에 호출해야 한다."""
        old_trades = self.daily_trades
        old_pnl = self.daily_pnl_pct
        old_shutdown = self.is_shutdown

        self.daily_trades = 0
        self.daily_pnl_pct = 0.0
        self.is_shutdown = False

        logger.info(
            "일일 카운터 리셋 | trades: %d->0 | pnl: %.2f%%->0 | shutdown: %s->False",
            old_trades,
            old_pnl,
            old_shutdown,
        )

    def check_vix(self, vix: float) -> bool:
        """VIX 기반 매매 가능 여부를 확인한다.

        Args:
            vix: 현재 VIX 지수 값.

        Returns:
            True이면 매매 가능, False이면 중단.
        """
        if vix >= self.vix_shutdown_threshold:
            logger.warning(
                "VIX 매매 중단 | vix=%.1f >= threshold=%d",
                vix,
                self.vix_shutdown_threshold,
            )
            return False

        logger.debug("VIX 정상 | vix=%.1f | threshold=%d", vix, self.vix_shutdown_threshold)
        return True

    def get_status(self) -> dict[str, Any]:
        """현재 하드 세이프티 상태를 딕셔너리로 반환한다.

        Returns:
            상태 정보 딕셔너리.
        """
        return {
            "is_shutdown": self.is_shutdown,
            "daily_trades": self.daily_trades,
            "max_daily_trades": self.max_daily_trades,
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_position_pct": self.max_position_pct,
            "max_total_position_pct": self.max_total_position_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "max_hold_days": self.max_hold_days,
            "vix_shutdown_threshold": self.vix_shutdown_threshold,
        }
