"""
텔레그램 매매 명령 처리.

매수/매도 주문의 확인 플로우를 관리한다:
  1. /buy [ticker] [amount] → 확인 대기
  2. /confirm → 주문 실행
  3. /cancel → 주문 취소
  4. 30초 타임아웃 시 자동 취소
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 대기 중 주문 타임아웃 (초)
_PENDING_TIMEOUT = 30.0


@dataclass
class PendingTrade:
    """대기 중인 매매 주문을 나타내는 데이터 클래스이다."""

    direction: str  # "buy" or "sell"
    ticker: str
    amount: str  # "$500" or "all" or "10" (shares)
    chat_id: str
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """타임아웃 여부를 확인한다."""
        return (time.time() - self.created_at) > _PENDING_TIMEOUT


class TradeCommandManager:
    """매매 명령의 확인 플로우를 관리하는 클래스이다.

    사용자별로 하나의 대기 주문만 허용한다.
    """

    def __init__(self) -> None:
        # python-telegram-bot의 비동기 핸들러는 단일 이벤트 루프에서 실행되므로
        # _pending dict에 대한 동시 접근 문제가 발생하지 않는다.
        self._pending: dict[str, PendingTrade] = {}
        self._trading_system: Any = None

    def set_trading_system(self, trading_system: Any) -> None:
        """TradingSystem 참조를 설정한다.

        Args:
            trading_system: TradingSystem 인스턴스.
        """
        self._trading_system = trading_system

    def create_pending(
        self,
        chat_id: str,
        direction: str,
        ticker: str,
        amount: str,
    ) -> PendingTrade:
        """대기 주문을 생성한다.

        기존 대기 주문이 있으면 새 주문으로 교체한다.

        Args:
            chat_id: 텔레그램 chat ID.
            direction: "buy" 또는 "sell".
            ticker: 종목 티커 (대문자).
            amount: 금액 또는 수량 문자열.

        Returns:
            생성된 PendingTrade 인스턴스.
        """
        trade = PendingTrade(
            direction=direction,
            ticker=ticker.upper(),
            amount=amount,
            chat_id=str(chat_id),
        )
        self._pending[str(chat_id)] = trade
        logger.info(
            "대기 주문 생성: chat_id=%s, %s %s %s",
            chat_id, direction, ticker, amount,
        )
        return trade

    def get_pending(self, chat_id: str) -> PendingTrade | None:
        """대기 중인 주문을 조회한다.

        만료된 주문은 자동으로 제거된다.

        Args:
            chat_id: 텔레그램 chat ID.

        Returns:
            PendingTrade 인스턴스 또는 None.
        """
        cid = str(chat_id)
        trade = self._pending.get(cid)
        if trade is None:
            return None
        if trade.is_expired:
            del self._pending[cid]
            logger.info("대기 주문 만료 제거: chat_id=%s", cid)
            return None
        return trade

    def cancel_pending(self, chat_id: str) -> bool:
        """대기 중인 주문을 취소한다.

        Args:
            chat_id: 텔레그램 chat ID.

        Returns:
            취소 성공 여부.
        """
        cid = str(chat_id)
        if cid in self._pending:
            del self._pending[cid]
            logger.info("대기 주문 취소: chat_id=%s", cid)
            return True
        return False

    async def execute_pending(self, chat_id: str) -> dict[str, Any]:
        """대기 중인 주문을 실행한다.

        Args:
            chat_id: 텔레그램 chat ID.

        Returns:
            실행 결과 딕셔너리.
            keys: success, message, trade_result (optional).

        Raises:
            ValueError: 대기 주문이 없거나 만료된 경우.
        """
        trade = self.get_pending(str(chat_id))
        if trade is None:
            return {
                "success": False,
                "message": "대기 중인 주문이 없습니다. /buy 또는 /sell로 먼저 주문을 생성하세요.",
            }

        # 대기 주문 제거
        self.cancel_pending(str(chat_id))

        if self._trading_system is None:
            return {
                "success": False,
                "message": "트레이딩 시스템이 초기화되지 않았습니다.",
            }

        try:
            logger.info(
                "주문 실행 시작: %s %s %s",
                trade.direction, trade.ticker, trade.amount,
            )

            # 금액 파싱
            amount_value = self._parse_amount(trade.amount)

            if trade.direction == "buy":
                result = await self._execute_buy(trade.ticker, amount_value)
            else:
                result = await self._execute_sell(trade.ticker, trade.amount)

            return {
                "success": result.get("success", False),
                "message": self._format_execution_result(trade, result),
                "trade_result": result,
            }

        except Exception as exc:
            logger.error("주문 실행 실패: %s", exc)
            return {
                "success": False,
                "message": f"주문 실행 중 오류 발생: {str(exc)[:200]}",
            }

    async def _execute_buy(self, ticker: str, amount_usd: float) -> dict[str, Any]:
        """매수 주문을 실행한다.

        Args:
            ticker: 종목 티커.
            amount_usd: 매수 금액(USD).

        Returns:
            실행 결과 딕셔너리.
        """
        try:
            ts = self._trading_system
            if ts.data_fetcher is None or ts.position_monitor is None or ts.order_manager is None:
                return {"success": False, "error": "트레이딩 시스템 모듈이 초기화되지 않았습니다."}

            # 현재가 조회
            price_data = await ts.data_fetcher.fetch_current_price(ticker)
            current_price = price_data.get("current_price", price_data.get("price", 0.0))

            if current_price <= 0:
                return {"success": False, "error": f"{ticker} 현재가 조회 실패"}

            # 수량 계산
            quantity = int(amount_usd / current_price)
            if quantity <= 0:
                return {"success": False, "error": f"금액 ${amount_usd}로는 {ticker} 1주도 매수할 수 없습니다 (현재가: ${current_price:.2f})"}

            # 포트폴리오 조회
            portfolio = await ts.position_monitor.get_portfolio_summary()
            try:
                vix = await ts.data_fetcher.get_vix()
                if vix <= 0.0:
                    vix = 20.0
            except Exception as exc:
                logger.debug("VIX 조회 실패, 기본값 20.0 사용: %s", exc)
                vix = 20.0

            # OrderManager를 통해 실행
            evaluation = {
                "approved": True,
                "ticker": ticker,
                "direction": "buy",
                "quantity": quantity,
                "price": current_price,
                "reason": "텔레그램 수동 매수 명령",
            }
            result = await ts.order_manager.execute_entry(
                evaluation, portfolio, vix,
            )
            if result is None:
                return {"success": False, "error": "주문이 안전 검증에 의해 거부되었습니다."}
            return result

        except Exception as exc:
            logger.error("매수 실행 실패 (%s): %s", ticker, exc)
            return {"success": False, "error": str(exc)}

    async def _execute_sell(self, ticker: str, amount_str: str) -> dict[str, Any]:
        """매도 주문을 실행한다.

        Args:
            ticker: 종목 티커.
            amount_str: "all" 또는 금액/수량 문자열.

        Returns:
            실행 결과 딕셔너리.
        """
        try:
            ts = self._trading_system
            if ts.position_monitor is None or ts.order_manager is None:
                return {"success": False, "error": "트레이딩 시스템 모듈이 초기화되지 않았습니다."}

            portfolio = await ts.position_monitor.get_portfolio_summary()
            positions = portfolio.get("positions", {})

            # 포지션이 dict인 경우와 list인 경우 모두 처리
            position = None
            if isinstance(positions, dict):
                position = positions.get(ticker)
            elif isinstance(positions, list):
                for p in positions:
                    if p.get("ticker") == ticker:
                        position = p
                        break

            if position is None:
                return {"success": False, "error": f"{ticker} 포지션을 보유하고 있지 않습니다."}

            # 매도 결정 생성
            decision = {
                "action": "sell",
                "ticker": ticker,
                "reason": "텔레그램 수동 매도 명령",
            }

            if amount_str.lower() != "all":
                # 부분 매도: 수량 지정
                try:
                    sell_qty = self._parse_amount(amount_str)
                except ValueError:
                    return {"success": False, "error": f"유효하지 않은 매도 수량: {amount_str}"}
                if sell_qty <= 0:
                    return {"success": False, "error": f"매도 수량은 0보다 커야 합니다: {amount_str}"}
                decision["quantity"] = int(sell_qty)

            result = await ts.order_manager.execute_exit(
                decision, position,
            )
            if result is None:
                return {"success": False, "error": "매도 주문 실행에 실패했습니다."}
            return result

        except Exception as exc:
            logger.error("매도 실행 실패 (%s): %s", ticker, exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _parse_amount(amount_str: str) -> float:
        """금액 문자열을 float로 변환한다.

        "$500", "500", "$1,000" 형식을 지원한다.

        Args:
            amount_str: 금액 문자열.

        Returns:
            금액(float).

        Raises:
            ValueError: 변환 불가 시.
        """
        cleaned = amount_str.replace("$", "").replace(",", "").strip()
        return float(cleaned)

    @staticmethod
    def _format_execution_result(trade: PendingTrade, result: dict[str, Any]) -> str:
        """실행 결과를 읽기 좋은 메시지로 포맷팅한다.

        Args:
            trade: 실행된 PendingTrade.
            result: 실행 결과 딕셔너리.

        Returns:
            포맷된 메시지 문자열.
        """
        direction_kr = "매수" if trade.direction == "buy" else "매도"

        if result.get("success", False):
            executed_price = result.get("price", result.get("executed_price", 0.0))
            executed_qty = result.get("quantity", result.get("executed_quantity", 0))
            return (
                f"\u2705 *{direction_kr} 체결 완료*\n\n"
                f"종목: {trade.ticker}\n"
                f"수량: {executed_qty}주\n"
                f"가격: ${executed_price:.2f}"
            )
        else:
            error = result.get("error", result.get("reason", "알 수 없는 오류"))
            return f"\u274c *{direction_kr} 실패*\n\n{error}"
