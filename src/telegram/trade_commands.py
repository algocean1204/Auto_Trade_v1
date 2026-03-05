"""TradeCommands -- 텔레그램을 통한 수동 매매 명령을 처리한다.

/buy SOXL 5, /sell QLD 3 같은 수동 매매 요청을 실행한다.
"""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient, OrderRequest
from src.common.logger import get_logger
from src.telegram.models import TradeCommandResult

logger = get_logger(__name__)

# 1회 주문 최대 수량 (안전장치)
_MAX_QTY: int = 100


def _validate_command(action: str, ticker: str, quantity: int) -> str | None:
    """매매 명령 유효성을 검증한다. 오류 시 메시지, 정상 시 None을 반환한다."""
    if action not in ("buy", "sell"):
        return f"잘못된 액션: {action} (buy/sell만 허용)"
    if not ticker or len(ticker) > 10:
        return f"잘못된 티커: {ticker}"
    if quantity <= 0 or quantity > _MAX_QTY:
        return f"수량 범위 초과: {quantity} (1~{_MAX_QTY})"
    return None


class TradeCommands:
    """수동 매매 명령 처리기이다."""

    def __init__(self, broker: BrokerClient | None = None) -> None:
        """BrokerClient를 주입받는다. None이면 실행 불가 모드이다."""
        self._broker = broker
        logger.info("TradeCommands 초기화 (broker=%s)", "연결됨" if broker else "없음")

    def set_broker(self, broker: BrokerClient) -> None:
        """브로커 클라이언트를 후행 주입한다."""
        self._broker = broker

    async def execute(self, trade_command: dict) -> TradeCommandResult:
        """매매 명령을 실행한다.

        Args:
            trade_command: {"action": "buy"|"sell", "ticker": str, "quantity": int}

        Returns:
            매매 실행 결과
        """
        action = trade_command.get("action", "")
        ticker = trade_command.get("ticker", "").upper()
        quantity = int(trade_command.get("quantity", 0))

        error = _validate_command(action, ticker, quantity)
        if error is not None:
            return TradeCommandResult(executed=False, message=error)

        if self._broker is None:
            return TradeCommandResult(executed=False, message="브로커 미연결")

        try:
            order = OrderRequest(
                ticker=ticker,
                side=action,  # type: ignore[arg-type]
                quantity=quantity,
                order_type="market",
            )
            result = await self._broker.place_order(order)
            logger.info("수동 매매 실행: %s %s x%d → %s", action, ticker, quantity, result.status)
            return TradeCommandResult(
                executed=(result.status == "filled"),
                order_result=result.model_dump(),
                message=result.message or result.status,
            )
        except Exception as exc:
            logger.exception("수동 매매 실패: %s %s", action, ticker)
            return TradeCommandResult(executed=False, message=str(exc))
