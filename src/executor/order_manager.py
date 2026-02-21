"""
주문 관리자

진입/청산 전략의 결정을 실제 KIS 주문으로 변환한다.
안전 검증 -> 주문 생성 -> 체결 추적 -> DB 기록

사용 흐름:
    1. execute_entry() : 진입 신호 -> SafetyChecker 검증 -> KIS 주문 -> DB 기록
    2. execute_exit()  : 청산 신호 -> KIS 매도 주문 -> DB 업데이트 (pnl 계산)
    3. execute_batch() : 여러 신호를 순차 처리
    4. cancel_unfilled_orders() : 미체결 주문 정리
"""

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.db.connection import get_session
from src.db.models import Trade
from src.executor.kis_client import KISAPIError, KISClient, KISOrderError
from src.safety.safety_checker import SafetyChecker
from src.tax.slippage_tracker import SlippageTracker
from src.tax.tax_tracker import TaxTracker
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

# 배치 주문 간 API 호출 제한 방지용 딜레이 (초)
_ORDER_TRACK_SLEEP: float = 0.5

# 미체결 주문 취소 시도 간 딜레이 (초)
_ORDER_CANCEL_RETRY_SLEEP: float = 0.3


class OrderManager:
    """진입/청산 주문을 관리한다.

    SafetyChecker를 통해 안전 검증을 수행하고,
    KISClient를 통해 실제 주문을 실행한 뒤,
    결과를 trades 테이블에 기록한다.

    Attributes:
        kis: KIS API 클라이언트.
        safety: 매매 전 안전 점검 통합 모듈.
        tax_tracker: 양도소득세 추적 인스턴스. None이면 기록 생략.
        slippage_tracker: 슬리피지 추적 인스턴스. None이면 기록 생략.
        pending_orders: 미체결 주문 추적 딕셔너리 (order_id -> 주문 정보).
    """

    def __init__(
        self,
        kis_client: KISClient,
        safety_checker: SafetyChecker,
        tax_tracker: TaxTracker | None = None,
        slippage_tracker: SlippageTracker | None = None,
    ) -> None:
        """OrderManager를 초기화한다.

        Args:
            kis_client: KIS API 클라이언트 인스턴스.
            safety_checker: SafetyChecker 인스턴스.
            tax_tracker: TaxTracker 인스턴스. 청산 후 세금 기록에 사용된다.
            slippage_tracker: SlippageTracker 인스턴스. 주문 체결 후 슬리피지 기록에 사용된다.
        """
        self.kis = kis_client
        self.safety = safety_checker
        self.tax_tracker = tax_tracker
        self.slippage_tracker = slippage_tracker
        self.pending_orders: dict[str, dict[str, Any]] = {}
        logger.info("OrderManager 초기화 완료")

    # ------------------------------------------------------------------
    # 진입 주문
    # ------------------------------------------------------------------

    async def execute_entry(
        self,
        entry_signal: dict[str, Any],
        portfolio: dict[str, Any],
        vix: float,
    ) -> dict[str, Any] | None:
        """진입 주문을 실행한다.

        1. SafetyChecker.pre_trade_check()로 안전 검증
        2. 통과 시 KIS 매수 주문 실행
        3. 주문 결과를 trades 테이블에 기록
        4. 실패 시 로깅 후 None 반환

        Args:
            entry_signal: EntryStrategy.evaluate_entry()의 결과 항목.
                필수 키: "ticker", "side", "quantity", "order_type",
                         "confidence", "direction", "regime".
            portfolio: 현재 포트폴리오 정보.
                필수 키: "positions", "cash", "total_value".
            vix: 현재 VIX 지수 값.

        Returns:
            주문 결과 딕셔너리 또는 실패 시 None::

                {
                    "order_id": str,
                    "trade_id": str,
                    "ticker": str,
                    "side": "buy",
                    "quantity": int,
                    "price": float | None,
                    "status": str,
                }
        """
        ticker = entry_signal.get("ticker", "UNKNOWN")
        quantity = entry_signal.get("quantity", 0)
        logger.info(
            "진입 주문 시작 | ticker=%s | qty=%d | confidence=%.2f",
            ticker, quantity, entry_signal.get("confidence", 0.0),
        )

        # 현재가 조회 (시장가 주문을 위한 참고 가격)
        try:
            price_data = await self.kis.get_overseas_price(ticker)
            current_price = price_data.get("current_price", 0.0)
        except KISAPIError as exc:
            logger.error("현재가 조회 실패 | ticker=%s | error=%s", ticker, exc)
            return None

        if current_price <= 0:
            logger.error("유효하지 않은 현재가 | ticker=%s | price=%.2f", ticker, current_price)
            return None

        # 1. 안전 검증
        order_for_check: dict[str, Any] = {
            "ticker": ticker,
            "side": "buy",
            "quantity": quantity,
            "price": current_price,
        }
        safety_result = await self.safety.pre_trade_check(
            order=order_for_check,
            portfolio=portfolio,
            vix=vix,
        )

        if not safety_result["allowed"]:
            logger.warning(
                "진입 안전 검증 실패 | ticker=%s | reason=%s",
                ticker,
                safety_result.get("block_reason"),
            )
            return None

        # 2. KIS 주문 실행
        order_type_code = "01" if entry_signal.get("order_type") == "market" else "00"
        price = None if order_type_code == "01" else current_price

        try:
            order_result = await self.kis.place_order(
                ticker=ticker,
                order_type=order_type_code,
                side="buy",
                quantity=quantity,
                price=price,
            )
        except (KISOrderError, KISAPIError) as exc:
            logger.error("KIS 매수 주문 실패 | ticker=%s | error=%s", ticker, exc)
            return None

        order_id = order_result.get("order_id", "")
        logger.info(
            "KIS 매수 주문 성공 | order_id=%s | ticker=%s | qty=%d",
            order_id, ticker, quantity,
        )

        # 거래 카운트 증가
        self.safety.safety.record_trade()

        # 미체결 주문 추적에 추가
        self.pending_orders[order_id] = {
            "order_id": order_id,
            "ticker": ticker,
            "side": "buy",
            "quantity": quantity,
            "price": current_price,
            "order_type": entry_signal.get("order_type", "market"),
            "created_at": datetime.now(tz=timezone.utc),
        }

        # 3. DB 기록
        trade_id = await self._record_trade_entry(order_result, entry_signal)

        # 4. 슬리피지 기록 (체결가와 참고가 비교)
        if self.slippage_tracker is not None and trade_id:
            filled_price = order_result.get("price", current_price) or current_price
            try:
                await self.slippage_tracker.record_slippage(
                    trade_id=trade_id,
                    ticker=ticker,
                    expected_price=current_price,
                    actual_price=float(filled_price),
                    volume=quantity,
                )
            except Exception as exc:
                logger.warning("슬리피지 기록 실패 (무시) | trade_id=%s | error=%s", trade_id, exc)

        return {
            "order_id": order_id,
            "trade_id": trade_id,
            "ticker": ticker,
            "side": "buy",
            "quantity": quantity,
            "price": current_price,
            "status": "submitted",
        }

    # ------------------------------------------------------------------
    # 청산 주문
    # ------------------------------------------------------------------

    async def execute_exit(
        self,
        exit_signal: dict[str, Any],
        position: dict[str, Any],
    ) -> dict[str, Any] | None:
        """청산 주문을 실행한다.

        매도는 안전 검증을 스킵한다 (항상 허용).
        KIS 매도 주문 후 trades 테이블을 업데이트한다.

        Args:
            exit_signal: ExitStrategy.check_exit_conditions()의 결과.
                필수 키: "action", "reason", "quantity", "trigger".
            position: 현재 보유 포지션 정보.
                필수 키: "ticker", "trade_id", "entry_price", "quantity".

        Returns:
            주문 결과 딕셔너리 또는 실패 시 None::

                {
                    "order_id": str,
                    "trade_id": str,
                    "ticker": str,
                    "side": "sell",
                    "quantity": int,
                    "price": float,
                    "status": str,
                }
        """
        ticker = position.get("ticker", "UNKNOWN")
        sell_quantity = exit_signal.get("quantity", 0)
        trigger = exit_signal.get("trigger", "unknown")
        trade_id = position.get("trade_id", "")
        # 포지션에 저장된 거래소 코드가 있으면 사용, 없으면 NASD 기본값
        exchange = position.get("exchange", "NASD")

        logger.info(
            "청산 주문 시작 | ticker=%s | qty=%d | trigger=%s | reason=%s",
            ticker, sell_quantity, trigger, exit_signal.get("reason", ""),
        )

        if sell_quantity <= 0:
            logger.warning("청산 수량이 0 이하 | ticker=%s", ticker)
            return None

        # 시장가 매도 주문 (모의투자 시 kis_client 내부에서 지정가로 자동 전환됨)
        try:
            order_result = await self.kis.place_order(
                ticker=ticker,
                order_type="01",  # 시장가 (모의투자 시 지정가로 자동 전환)
                side="sell",
                quantity=sell_quantity,
                exchange=exchange,
            )
        except (KISOrderError, KISAPIError) as exc:
            logger.error("KIS 매도 주문 실패 | ticker=%s | error=%s", ticker, exc)
            return None

        order_id = order_result.get("order_id", "")
        logger.info(
            "KIS 매도 주문 성공 | order_id=%s | ticker=%s | qty=%d | trigger=%s",
            order_id, ticker, sell_quantity, trigger,
        )

        # 거래 카운트 증가
        self.safety.safety.record_trade()

        # 현재가 조회 (exit_price 기록용)
        try:
            price_data = await self.kis.get_overseas_price(ticker)
            exit_price = price_data.get("current_price", 0.0)
        except KISAPIError:
            exit_price = 0.0
            logger.warning("청산 시점 현재가 조회 실패 | ticker=%s", ticker)

        # DB 업데이트
        if trade_id:
            await self._record_trade_exit(trade_id, order_result, exit_signal, exit_price)

        # 청산 후 슬리피지 기록 (시장가 매도의 실제 체결가 vs 참고가 비교)
        if self.slippage_tracker is not None and trade_id and exit_price > 0:
            entry_price = position.get("entry_price", exit_price)
            try:
                await self.slippage_tracker.record_slippage(
                    trade_id=trade_id,
                    ticker=ticker,
                    expected_price=float(entry_price),
                    actual_price=exit_price,
                    volume=sell_quantity,
                )
            except Exception as exc:
                logger.warning("청산 슬리피지 기록 실패 (무시) | trade_id=%s | error=%s", trade_id, exc)

        # 청산 후 세금 기록 (양도소득세 추적)
        if self.tax_tracker is not None and trade_id:
            entry_price = position.get("entry_price", 0.0)
            pnl_usd = (exit_price - entry_price) * sell_quantity if exit_price > 0 and entry_price > 0 else 0.0
            # FX 환율: 기본 1300원/USD (실시간 환율 미조회 시 fallback)
            fx_rate = position.get("fx_rate", 1300.0)
            try:
                await self.tax_tracker.record_trade_tax(
                    trade_id=trade_id,
                    pnl_usd=pnl_usd,
                    fx_rate=float(fx_rate),
                )
            except Exception as exc:
                logger.warning("세금 기록 실패 (무시) | trade_id=%s | error=%s", trade_id, exc)

        return {
            "order_id": order_id,
            "trade_id": trade_id,
            "ticker": ticker,
            "side": "sell",
            "quantity": sell_quantity,
            "price": exit_price,
            "status": "submitted",
        }

    # ------------------------------------------------------------------
    # 배치 주문
    # ------------------------------------------------------------------

    async def execute_batch(
        self,
        signals: list[dict[str, Any]],
        portfolio: dict[str, Any],
        vix: float,
    ) -> list[dict[str, Any]]:
        """여러 진입/청산 신호를 순차 처리한다.

        KIS API 초당 호출 제한을 고려하여 각 주문 사이에
        0.5초 딜레이를 둔다.

        Args:
            signals: 진입/청산 신호 리스트.
                각 항목에는 "type" 키가 있어야 함 ("entry" 또는 "exit").
                "entry" 타입: entry_signal + portfolio 정보 포함.
                "exit" 타입: exit_signal + position 정보 포함.
            portfolio: 현재 포트폴리오 정보.
            vix: 현재 VIX 지수 값.

        Returns:
            실행된 주문 결과 리스트.
        """
        results: list[dict[str, Any]] = []
        logger.info("배치 주문 시작 | 총 %d건", len(signals))

        for i, signal in enumerate(signals):
            signal_type = signal.get("type", "entry")
            ticker = signal.get("ticker", signal.get("entry_signal", {}).get("ticker", "UNKNOWN"))

            logger.info(
                "배치 주문 [%d/%d] | type=%s | ticker=%s",
                i + 1, len(signals), signal_type, ticker,
            )

            result: dict[str, Any] | None = None
            if signal_type == "entry":
                entry_signal = signal.get("entry_signal", signal)
                result = await self.execute_entry(entry_signal, portfolio, vix)
            elif signal_type == "exit":
                exit_signal = signal.get("exit_signal", signal)
                position = signal.get("position", {})
                result = await self.execute_exit(exit_signal, position)
            else:
                logger.warning("알 수 없는 신호 타입 | type=%s", signal_type)

            if result is not None:
                results.append(result)

            # API 호출 제한 방지를 위한 딜레이
            if i < len(signals) - 1:
                await asyncio.sleep(_ORDER_TRACK_SLEEP)

        logger.info(
            "배치 주문 완료 | 성공=%d/%d건",
            len(results), len(signals),
        )
        return results

    # ------------------------------------------------------------------
    # 미체결 주문 관리
    # ------------------------------------------------------------------

    async def check_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태를 확인한다.

        KIS 체결 내역 API를 조회하여 해당 주문의 상태를 반환한다.

        Args:
            order_id: 주문 번호.

        Returns:
            주문 상태 딕셔너리::

                {
                    "order_id": str,
                    "status": "filled" | "partial" | "pending" | "cancelled",
                    "filled_quantity": int,
                    "filled_price": float,
                }
        """
        try:
            history = await self.kis.get_order_history()
        except KISAPIError as exc:
            logger.error("주문 내역 조회 실패 | error=%s", exc)
            return {
                "order_id": order_id,
                "status": "unknown",
                "filled_quantity": 0,
                "filled_price": 0.0,
            }

        for record in history:
            if record.get("order_id") == order_id:
                status = record.get("status", "pending")
                filled_qty = record.get("filled_quantity", 0)
                total_qty = record.get("quantity", 0)

                # 부분 체결 감지
                if status == "filled" and 0 < filled_qty < total_qty:
                    status = "partial"

                return {
                    "order_id": order_id,
                    "status": status,
                    "filled_quantity": filled_qty,
                    "filled_price": record.get("filled_price", 0.0),
                }

        logger.warning("주문 내역에서 order_id 미발견 | order_id=%s", order_id)
        return {
            "order_id": order_id,
            "status": "unknown",
            "filled_quantity": 0,
            "filled_price": 0.0,
        }

    async def cancel_unfilled_orders(self, max_wait_minutes: int = 5) -> list[dict[str, Any]]:
        """미체결 주문을 정리한다.

        pending_orders에서 max_wait_minutes 이상 경과한 미체결 주문을
        KIS API를 통해 취소한다.

        Args:
            max_wait_minutes: 최대 대기 시간(분). 기본 5분.

        Returns:
            취소된 주문 리스트.
        """
        cancelled: list[dict[str, Any]] = []
        now = datetime.now(tz=timezone.utc)
        orders_to_remove: list[str] = []

        logger.info(
            "미체결 주문 정리 시작 | 추적 중인 주문=%d건 | max_wait=%d분",
            len(self.pending_orders), max_wait_minutes,
        )

        for order_id, order_info in self.pending_orders.items():
            created_at = order_info.get("created_at", now)
            elapsed_minutes = (now - created_at).total_seconds() / 60.0

            if elapsed_minutes < max_wait_minutes:
                continue

            # 주문 상태 확인
            status_info = await self.check_order_status(order_id)
            status = status_info.get("status", "unknown")

            if status in ("filled", "cancelled"):
                orders_to_remove.append(order_id)
                logger.debug(
                    "주문 이미 %s | order_id=%s", status, order_id,
                )
                continue

            # 미체결 주문 취소
            ticker = order_info.get("ticker", "")
            quantity = order_info.get("quantity", 0)
            try:
                cancel_result = await self.kis.cancel_order(
                    order_id=order_id,
                    ticker=ticker,
                    quantity=quantity,
                )
                cancelled.append({
                    "order_id": order_id,
                    "ticker": ticker,
                    "quantity": quantity,
                    "elapsed_minutes": round(elapsed_minutes, 1),
                    "cancel_result": cancel_result,
                })
                orders_to_remove.append(order_id)
                logger.info(
                    "미체결 주문 취소 | order_id=%s | ticker=%s | elapsed=%.1f분",
                    order_id, ticker, elapsed_minutes,
                )
            except (KISOrderError, KISAPIError) as exc:
                logger.error(
                    "미체결 주문 취소 실패 | order_id=%s | error=%s",
                    order_id, exc,
                )

            await asyncio.sleep(_ORDER_CANCEL_RETRY_SLEEP)

        # 처리 완료된 주문 제거
        for oid in orders_to_remove:
            self.pending_orders.pop(oid, None)

        logger.info("미체결 주문 정리 완료 | 취소=%d건", len(cancelled))
        return cancelled

    # ------------------------------------------------------------------
    # DB 기록
    # ------------------------------------------------------------------

    async def _record_trade_entry(
        self,
        order_result: dict[str, Any],
        entry_signal: dict[str, Any],
    ) -> str:
        """매매 진입을 DB에 기록한다.

        trades 테이블에 새 레코드를 생성한다.

        Args:
            order_result: KIS 주문 결과.
            entry_signal: 진입 신호 정보.

        Returns:
            생성된 trade ID.
        """
        trade_id = str(uuid4())
        ticker = entry_signal.get("ticker", "")
        direction = entry_signal.get("direction", "bull")
        confidence = entry_signal.get("confidence", 0.0)
        regime = entry_signal.get("regime", "")

        # 진입 가격: 체결가 또는 참고 가격
        entry_price = order_result.get("price", 0.0)
        if entry_price is None or entry_price <= 0:
            entry_price = entry_signal.get("price", 0.0)

        try:
            async with get_session() as session:
                trade = Trade(
                    id=trade_id,
                    ticker=ticker,
                    direction=direction,
                    entry_price=entry_price,
                    entry_at=datetime.now(tz=timezone.utc),
                    ai_confidence=confidence,
                    ai_signals=[{
                        "order_id": order_result.get("order_id", ""),
                        "reason": entry_signal.get("reason", ""),
                        "indicator_direction": entry_signal.get("indicator_direction", ""),
                        "indicator_confidence": entry_signal.get("indicator_confidence", 0.0),
                        "quantity": entry_signal.get("quantity", 0),
                    }],
                    market_regime=regime,
                )
                session.add(trade)

            logger.info(
                "Trade 진입 DB 기록 | trade_id=%s | ticker=%s | price=%.2f | direction=%s",
                trade_id, ticker, entry_price, direction,
            )
        except Exception as exc:
            logger.error(
                "Trade 진입 DB 기록 실패 | ticker=%s | error=%s", ticker, exc,
            )

        return trade_id

    async def _record_trade_exit(
        self,
        trade_id: str,
        order_result: dict[str, Any],
        exit_signal: dict[str, Any],
        exit_price: float,
    ) -> None:
        """매매 청산을 DB에 기록한다.

        trades 테이블의 기존 레코드를 업데이트한다
        (exit_price, exit_at, pnl_pct, hold_minutes, exit_reason).

        Args:
            trade_id: 업데이트 대상 trade ID.
            order_result: KIS 주문 결과.
            exit_signal: 청산 신호 정보.
            exit_price: 청산 시점의 현재가.
        """
        exit_reason = exit_signal.get("trigger", "unknown")
        now = datetime.now(tz=timezone.utc)

        try:
            async with get_session() as session:
                trade = await session.get(Trade, trade_id)
                if trade is None:
                    logger.warning("Trade 레코드 미발견 | trade_id=%s", trade_id)
                    return

                trade.exit_price = exit_price
                trade.exit_at = now
                trade.exit_reason = exit_reason

                # PnL 계산
                if trade.entry_price > 0 and exit_price > 0:
                    trade.pnl_pct = round(
                        ((exit_price - trade.entry_price) / trade.entry_price) * 100.0,
                        4,
                    )
                    quantity = exit_signal.get("quantity", 0)
                    trade.pnl_amount = round(
                        (exit_price - trade.entry_price) * quantity,
                        2,
                    )

                # 보유 시간 계산 (분)
                if trade.entry_at:
                    entry_aware = trade.entry_at
                    if entry_aware.tzinfo is None:
                        entry_aware = entry_aware.replace(tzinfo=timezone.utc)
                    delta = now - entry_aware
                    trade.hold_minutes = int(delta.total_seconds() / 60)

                # 일일 PnL 업데이트
                if trade.pnl_pct is not None:
                    current_daily_pnl = self.safety.safety.daily_pnl_pct + trade.pnl_pct
                    self.safety.safety.update_daily_pnl(current_daily_pnl)

            logger.info(
                "Trade 청산 DB 기록 | trade_id=%s | ticker=%s | "
                "exit_price=%.2f | pnl=%.2f%% | reason=%s | hold=%d분",
                trade_id,
                trade.ticker if trade else "?",
                exit_price,
                trade.pnl_pct if trade and trade.pnl_pct else 0.0,
                exit_reason,
                trade.hold_minutes if trade and trade.hold_minutes else 0,
            )
        except Exception as exc:
            logger.error(
                "Trade 청산 DB 기록 실패 | trade_id=%s | error=%s",
                trade_id, exc,
            )
