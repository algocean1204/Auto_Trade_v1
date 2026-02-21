"""
포지션 모니터

보유 포지션을 실시간으로 추적하고 청산 조건을 감지한다.
15분 루프의 메인 스케줄러에서 monitor_all()을 호출하여
전체 포지션에 대해 ExitStrategy + HardSafety 검증을 수행한다.

사용 흐름:
    1. sync_positions()   : KIS 잔고와 로컬 positions 동기화
    2. monitor_all()      : 모든 포지션 모니터링 + 청산 조건 감지 + 자동 청산
    3. get_portfolio_summary() : 대시보드용 포트폴리오 요약
"""

from datetime import datetime, timezone
from typing import Any

from src.executor.kis_client import KISAPIError, KISClient
from src.executor.order_manager import OrderManager
from src.safety.hard_safety import HardSafety
from src.strategy.exit_strategy import ExitStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PositionMonitor:
    """보유 포지션을 실시간 추적하고 청산 조건을 감지한다.

    KIS 잔고와 로컬 포지션을 동기화하며,
    ExitStrategy와 HardSafety를 통해 청산 조건을 확인하고,
    OrderManager를 통해 자동 청산을 실행한다.

    Attributes:
        kis: KIS API 클라이언트.
        exit_strategy: 청산 전략 인스턴스.
        order_manager: 주문 관리자 인스턴스.
        safety: 하드 세이프티 인스턴스.
        positions: 로컬 포지션 추적 딕셔너리 (ticker -> position).
    """

    def __init__(
        self,
        kis_client: KISClient,
        exit_strategy: ExitStrategy,
        order_manager: OrderManager,
        hard_safety: HardSafety,
    ) -> None:
        """PositionMonitor를 초기화한다.

        Args:
            kis_client: KIS API 클라이언트.
            exit_strategy: 청산 전략 인스턴스.
            order_manager: 주문 관리자 인스턴스.
            hard_safety: 하드 세이프티 인스턴스.
        """
        self.kis = kis_client
        self.exit_strategy = exit_strategy
        self.order_manager = order_manager
        self.safety = hard_safety
        self.positions: dict[str, dict[str, Any]] = {}
        logger.info("PositionMonitor 초기화 완료")

    @classmethod
    def create_readonly(cls, kis_client: KISClient) -> "PositionMonitor":
        """조회 전용 PositionMonitor를 생성한다 (거래 실행 불가).

        대시보드 전용 모드에서 KIS 잔고/포지션 조회에만 사용한다.
        exit_strategy, order_manager, safety는 None으로 설정되어
        monitor_all() 호출 시 AttributeError가 발생하지만,
        get_portfolio_summary()와 get_all_positions()는 정상 동작한다.

        Args:
            kis_client: KIS API 클라이언트.

        Returns:
            조회 전용 PositionMonitor 인스턴스.
        """
        instance = cls.__new__(cls)
        instance.kis = kis_client
        instance.exit_strategy = None
        instance.order_manager = None
        instance.safety = None
        instance.positions = {}
        logger.info("PositionMonitor (read-only) 초기화 완료")
        return instance

    # ------------------------------------------------------------------
    # 포지션 동기화
    # ------------------------------------------------------------------

    async def sync_positions(self) -> dict[str, dict[str, Any]]:
        """KIS 잔고와 로컬 포지션을 동기화한다.

        KIS get_balance()를 호출하여 실제 보유 종목을 가져오고,
        로컬 positions를 업데이트한다.
        로컬에만 있고 KIS에 없는 포지션은 제거한다.

        Returns:
            동기화된 포지션 딕셔너리 (ticker -> position).
        """
        logger.info("포지션 동기화 시작")

        try:
            balance = await self.kis.get_balance()
        except KISAPIError as exc:
            logger.error("잔고 조회 실패 | error=%s", exc)
            return self.positions

        if not balance or not isinstance(balance, dict):
            logger.error("잔고 조회 결과가 유효하지 않음: %s", type(balance))
            return self.positions

        kis_positions: dict[str, dict[str, Any]] = {}
        for pos in balance.get("positions", []):
            ticker = pos.get("ticker", "")
            if not ticker:
                continue
            kis_positions[ticker] = pos

        # KIS 잔고 기반으로 로컬 포지션 업데이트
        for ticker, kis_pos in kis_positions.items():
            if ticker in self.positions:
                # 기존 포지션 업데이트 (로컬의 메타 정보는 유지)
                local = self.positions[ticker]
                local["quantity"] = kis_pos["quantity"]
                local["avg_price"] = kis_pos["avg_price"]
                local["current_price"] = kis_pos["current_price"]
                local["pnl_pct"] = kis_pos.get("pnl_pct", 0.0)
                local["pnl_amount"] = kis_pos.get("pnl_amount", 0.0)
                local["market_value"] = kis_pos["quantity"] * kis_pos["current_price"]
                local["exchange"] = kis_pos.get("exchange", "NASD")
            else:
                # 새 포지션 (수동 매매 또는 다른 채널로 진입한 경우)
                self.positions[ticker] = {
                    "ticker": ticker,
                    "name": kis_pos.get("name", ""),
                    "quantity": kis_pos["quantity"],
                    "avg_price": kis_pos["avg_price"],
                    "entry_price": kis_pos["avg_price"],
                    "current_price": kis_pos["current_price"],
                    "highest_price": kis_pos["current_price"],
                    "pnl_pct": kis_pos.get("pnl_pct", 0.0),
                    "pnl_amount": kis_pos.get("pnl_amount", 0.0),
                    "market_value": kis_pos["quantity"] * kis_pos["current_price"],
                    "exchange": kis_pos.get("exchange", "NASD"),
                    "direction": "bull",
                    "trade_id": "",
                    "entry_at": datetime.now(tz=timezone.utc),
                    "hold_days": 0,
                }
                logger.info(
                    "새 포지션 감지 | ticker=%s | qty=%d | avg_price=%.2f",
                    ticker, kis_pos["quantity"], kis_pos["avg_price"],
                )

        # KIS에 없는 로컬 포지션 제거 (이미 청산 완료된 포지션)
        removed_tickers = [t for t in self.positions if t not in kis_positions]
        for ticker in removed_tickers:
            logger.info("포지션 제거 (KIS 잔고에 없음) | ticker=%s", ticker)
            del self.positions[ticker]

        logger.info(
            "포지션 동기화 완료 | 보유=%d종목 | cash=%.2f",
            len(self.positions),
            balance.get("cash_balance", 0.0),
        )
        return self.positions

    # ------------------------------------------------------------------
    # 전체 모니터링
    # ------------------------------------------------------------------

    async def monitor_all(
        self, regime: str, vix: float
    ) -> list[dict[str, Any]]:
        """모든 포지션을 모니터링하고 청산 조건을 실행한다.

        메인 루프(15분 주기)에서 호출된다.

        1. 각 포지션의 현재가 조회
        2. highest_price 업데이트 (트레일링 스탑용)
        3. ExitStrategy.check_exit_conditions() 실행
        4. 청산 조건 충족 시 OrderManager.execute_exit() 실행
        5. HardSafety.check_position() 추가 검증

        Args:
            regime: 현재 시장 레짐 ("strong_bull", "mild_bull", ...).
            vix: 현재 VIX 지수 값.

        Returns:
            실행된 청산 주문 리스트.
        """
        exit_orders: list[dict[str, Any]] = []
        tickers = list(self.positions.keys())

        logger.info(
            "포지션 모니터링 시작 | 종목=%d | regime=%s | vix=%.1f",
            len(tickers), regime, vix,
        )

        for ticker in tickers:
            position = self.positions.get(ticker)
            if position is None:
                continue

            # 1. 현재가 조회
            try:
                price_data = await self.kis.get_overseas_price(
                    ticker, exchange=self._ticker_to_price_exchange(position)
                )
                current_price = price_data.get("current_price", 0.0)
            except KISAPIError as exc:
                logger.warning("현재가 조회 실패 | ticker=%s | error=%s", ticker, exc)
                continue

            if current_price <= 0:
                logger.warning("유효하지 않은 현재가 | ticker=%s | price=%.2f", ticker, current_price)
                continue

            # 포지션 현재가 업데이트
            position["current_price"] = current_price
            position["market_value"] = position["quantity"] * current_price

            # 2. highest_price 업데이트 (트레일링 스탑용)
            ExitStrategy.update_highest_price(position, current_price)

            # 3. ExitStrategy 청산 조건 체크
            exit_signal = self.exit_strategy.check_exit_conditions(
                position=position,
                current_price=current_price,
                regime=regime,
                vix=vix,
            )

            # 4. HardSafety 추가 검증 (ExitStrategy가 청산을 지시하지 않은 경우)
            if exit_signal is None:
                safety_check = self.safety.check_position({
                    "ticker": ticker,
                    "quantity": position["quantity"],
                    "avg_price": position.get("avg_price", position.get("entry_price", 0.0)),
                    "current_price": current_price,
                    "days_held": position.get("hold_days", 0),
                })
                if safety_check is not None:
                    exit_signal = {
                        "action": "sell",
                        "reason": safety_check["reason"],
                        "quantity": safety_check["quantity"],
                        "urgency": "immediate",
                        "trigger": "hard_safety",
                    }
                    logger.warning(
                        "HardSafety 청산 발동 | ticker=%s | reason=%s",
                        ticker, safety_check["reason"],
                    )

            # 5. 청산 실행
            if exit_signal is not None:
                result = await self.order_manager.execute_exit(
                    exit_signal=exit_signal,
                    position=position,
                )
                if result is not None:
                    exit_orders.append(result)
                    logger.info(
                        "청산 실행 완료 | ticker=%s | trigger=%s | qty=%d",
                        ticker,
                        exit_signal.get("trigger", "unknown"),
                        exit_signal.get("quantity", 0),
                    )

        logger.info(
            "포지션 모니터링 완료 | 청산 실행=%d건", len(exit_orders),
        )
        return exit_orders

    # ------------------------------------------------------------------
    # 포트폴리오 요약
    # ------------------------------------------------------------------

    async def get_portfolio_summary(self) -> dict[str, Any]:
        """포트폴리오 요약 정보를 반환한다.

        KIS 잔고를 조회하여 현금, 포지션, 총 자산 등을 반환한다.

        Returns:
            포트폴리오 요약::

                {
                    "total_value": float,
                    "cash": float,
                    "positions": list[dict],
                    "total_pnl_pct": float,
                    "position_count": int,
                }
        """
        try:
            balance = await self.kis.get_balance()
        except KISAPIError as exc:
            logger.error("잔고 조회 실패 (포트폴리오 요약) | error=%s", exc)
            # 로컬 데이터로 대체
            total_position_value = sum(
                pos.get("market_value", 0.0) for pos in self.positions.values()
            )
            return {
                "total_value": total_position_value,
                "cash": 0.0,
                "positions": list(self.positions.values()),
                "total_pnl_pct": 0.0,
                "position_count": len(self.positions),
            }

        cash = balance.get("cash_balance", 0.0)
        total_eval = balance.get("total_evaluation", 0.0)
        total_pnl = balance.get("total_pnl", 0.0)

        # 포지션별 정보 정리
        positions_list: list[dict[str, Any]] = []
        for pos in balance.get("positions", []):
            ticker = pos.get("ticker", "")
            local_pos = self.positions.get(ticker, {})
            positions_list.append({
                "ticker": ticker,
                "name": pos.get("name", ""),
                "quantity": pos.get("quantity", 0),
                "avg_price": pos.get("avg_price", 0.0),
                "current_price": pos.get("current_price", 0.0),
                "market_value": pos.get("quantity", 0) * pos.get("current_price", 0.0),
                "pnl_pct": pos.get("pnl_pct", 0.0),
                "pnl_amount": pos.get("pnl_amount", 0.0),
                "hold_days": local_pos.get("hold_days", 0),
                "direction": local_pos.get("direction", "bull"),
                "trade_id": local_pos.get("trade_id", ""),
            })

        total_value = total_eval if total_eval > 0 else cash
        total_pnl_pct = 0.0
        if total_value > 0 and total_pnl != 0:
            invested = total_value - cash
            if invested > 0:
                total_pnl_pct = round((total_pnl / invested) * 100.0, 2)

        return {
            "total_value": total_value,
            "cash": cash,
            "positions": positions_list,
            "total_pnl_pct": total_pnl_pct,
            "position_count": len(positions_list),
        }

    # ------------------------------------------------------------------
    # 개별 포지션 조회
    # ------------------------------------------------------------------

    def get_position(self, ticker: str) -> dict[str, Any] | None:
        """특정 종목 포지션을 조회한다.

        Args:
            ticker: 종목 심볼.

        Returns:
            포지션 딕셔너리 또는 None.
        """
        return self.positions.get(ticker.upper())

    def get_all_positions(self) -> list[dict[str, Any]]:
        """전체 포지션 리스트를 반환한다.

        Returns:
            포지션 딕셔너리 리스트.
        """
        return list(self.positions.values())

    # ------------------------------------------------------------------
    # 포지션 메타 데이터 설정
    # ------------------------------------------------------------------

    def set_position_meta(
        self,
        ticker: str,
        trade_id: str = "",
        entry_at: datetime | None = None,
        direction: str = "bull",
        hold_days: int = 0,
        highest_price: float = 0.0,
    ) -> None:
        """로컬 포지션에 메타 데이터를 설정한다.

        execute_entry()에서 주문 성공 후 호출하여
        trade_id, entry_at, direction 등을 기록한다.

        Args:
            ticker: 종목 심볼.
            trade_id: DB trade ID.
            entry_at: 진입 시각.
            direction: 매매 방향 ("bull" 또는 "bear").
            hold_days: 보유 일수.
            highest_price: 최고가 (트레일링 스탑용).
        """
        ticker = ticker.upper()
        if ticker not in self.positions:
            logger.warning("포지션 메타 설정 실패: 종목 없음 | ticker=%s", ticker)
            return

        pos = self.positions[ticker]
        if trade_id:
            pos["trade_id"] = trade_id
        if entry_at is not None:
            pos["entry_at"] = entry_at
        pos["direction"] = direction
        pos["hold_days"] = hold_days
        if highest_price > 0:
            pos["highest_price"] = highest_price

        logger.debug(
            "포지션 메타 설정 | ticker=%s | trade_id=%s | direction=%s | hold_days=%d",
            ticker, trade_id, direction, hold_days,
        )

    def update_hold_days(self) -> None:
        """모든 포지션의 보유일수를 업데이트한다.

        entry_at 기준으로 경과 일수를 계산한다.
        매일 장 시작 전에 호출해야 한다.
        """
        now = datetime.now(tz=timezone.utc)
        for ticker, pos in self.positions.items():
            entry_at = pos.get("entry_at")
            if entry_at is None:
                continue
            if entry_at.tzinfo is None:
                entry_at = entry_at.replace(tzinfo=timezone.utc)
            delta = now - entry_at
            pos["hold_days"] = delta.days
            logger.debug(
                "보유일수 업데이트 | ticker=%s | hold_days=%d",
                ticker, pos["hold_days"],
            )

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _ticker_to_price_exchange(position: dict[str, Any]) -> str:
        """포지션의 exchange 코드를 시세 조회용 코드로 변환한다.

        KIS 잔고 API의 exchange 코드와 시세 API의 exchange 코드가 다르다.
        "NASD" -> "NAS", "NYSE" -> "NYS", "AMEX" -> "AMS"

        Args:
            position: 포지션 딕셔너리.

        Returns:
            시세 조회용 거래소 코드.
        """
        exchange_map = {
            "NASD": "NAS",
            "NYSE": "NYS",
            "AMEX": "AMS",
            "NAS": "NAS",
            "NYS": "NYS",
            "AMS": "AMS",
        }
        exchange = position.get("exchange", "NASD")
        return exchange_map.get(exchange, "NAS")
