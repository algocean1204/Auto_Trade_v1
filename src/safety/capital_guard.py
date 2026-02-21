"""
자본금 안전 검증 모듈 (Addendum 15)

절대 규칙:
    1. 잔액 범위 내 현물만 거래 (주문 금액 > 가용 현금이면 거부)
    2. 신용/마진 완전 금지 (증거금 비율 100% 미만이면 거부)
    3. 달러 전용 주문 검증 (KRW 주문 시도 시 거부)
"""

from typing import Any

from src.db.connection import get_session
from src.db.models import CapitalGuardLog
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
REQUIRED_MARGIN_RATIO: float = 100.0
ALLOWED_CURRENCY: str = "USD"


class CapitalGuard:
    """자본금 절대 규칙을 적용한다.

    잔액 초과 주문, 신용/마진 거래, KRW 주문을 원천 차단한다.
    모든 검증 결과는 capital_guard_log 테이블에 기록된다.

    이 클래스의 모든 public 메서드는 try/except로 감싸져 있어
    내부 에러가 시스템 크래시로 이어지지 않는다.
    검증 실패 시 안전 측으로 판단하여 주문을 거부한다.
    """

    def __init__(self) -> None:
        """CapitalGuard를 초기화한다."""
        logger.info("CapitalGuard 초기화 완료")

    # ------------------------------------------------------------------
    # 통합 주문 검증
    # ------------------------------------------------------------------

    async def validate_order(
        self, order: dict, account_info: dict
    ) -> tuple[bool, str]:
        """주문을 자본금 안전 규칙으로 종합 검증한다.

        1. 통화 검증 (USD만 허용)
        2. 마진 상태 확인 (100% 이상만 허용)
        3. 잔액 범위 검증 (현금 초과 주문 거부)

        매도 주문은 통화 검증만 수행하고 나머지는 통과시킨다.

        Args:
            order: 주문 정보 딕셔너리.
                필수 키: "ticker", "side", "quantity", "price".
                선택 키: "currency" (기본 "USD").
            account_info: 계좌 정보 딕셔너리.
                필수 키: "cash_balance" (float, USD 가용 현금),
                         "margin_ratio" (float, 증거금 비율 %).
                선택 키: "currency" (기본 "USD").

        Returns:
            (passed, reason) 튜플.
            passed가 True이면 주문 허용, False이면 거부와 사유.
        """
        try:
            # 1. 통화 검증
            currency_ok = await self.validate_currency(order)
            if not currency_ok:
                reason = (
                    f"KRW 주문 불가: USD 전용 계좌. "
                    f"주문 통화={order.get('currency', 'N/A')}"
                )
                logger.warning(
                    "주문 거부 [currency] | ticker=%s | %s",
                    order.get("ticker"), reason,
                )
                await self.log_check(
                    check_type="currency_validation",
                    passed=False,
                    details={"ticker": order.get("ticker"), "reason": reason},
                )
                return False, reason

            # 매도 주문은 잔액/마진 검증 없이 허용
            side = order.get("side", "").lower()
            if side == "sell":
                await self.log_check(
                    check_type="order_validation",
                    passed=True,
                    details={"ticker": order.get("ticker"), "side": "sell"},
                )
                return True, "매도 주문 허용"

            # 2. 마진 상태 확인
            margin_ok = await self.check_margin_status(account_info)
            if not margin_ok:
                margin_ratio = account_info.get("margin_ratio", 0.0)
                reason = (
                    f"신용/마진 거래 금지: 증거금 비율 "
                    f"{margin_ratio:.1f}% < {REQUIRED_MARGIN_RATIO}%"
                )
                logger.warning(
                    "주문 거부 [margin] | ticker=%s | %s",
                    order.get("ticker"), reason,
                )
                await self.log_check(
                    check_type="margin_validation",
                    passed=False,
                    details={
                        "ticker": order.get("ticker"),
                        "margin_ratio": margin_ratio,
                        "reason": reason,
                    },
                )
                return False, reason

            # 3. 잔액 범위 검증
            quantity = order.get("quantity", 0)
            price = order.get("price", 0.0)
            order_value = quantity * price
            cash_balance = account_info.get("cash_balance", 0.0)

            if order_value > cash_balance:
                reason = (
                    f"잔액 초과: 주문금액 ${order_value:,.2f} > "
                    f"가용현금 ${cash_balance:,.2f}"
                )
                logger.warning(
                    "주문 거부 [balance] | ticker=%s | %s",
                    order.get("ticker"), reason,
                )
                await self.log_check(
                    check_type="balance_validation",
                    passed=False,
                    details={
                        "ticker": order.get("ticker"),
                        "order_value": order_value,
                        "cash_balance": cash_balance,
                        "reason": reason,
                    },
                )
                return False, reason

            # 모두 통과
            logger.debug(
                "주문 통과 [capital_guard] | ticker=%s | "
                "order=$%.2f | cash=$%.2f",
                order.get("ticker"), order_value, cash_balance,
            )
            await self.log_check(
                check_type="order_validation",
                passed=True,
                details={
                    "ticker": order.get("ticker"),
                    "order_value": order_value,
                    "cash_balance": cash_balance,
                },
            )
            return True, "통과"

        except Exception as exc:
            logger.error(
                "CapitalGuard 주문 검증 에러 | ticker=%s | error=%s",
                order.get("ticker"), exc,
            )
            # 에러 발생 시 안전 측으로 판단하여 거부
            return False, f"자본금 검증 중 에러 발생: {exc}"

    # ------------------------------------------------------------------
    # 개별 검증
    # ------------------------------------------------------------------

    async def check_margin_status(self, account_info: dict) -> bool:
        """증거금 비율이 100% 이상인지 확인한다.

        100% 미만이면 신용/마진 거래 상태이므로 매매를 차단한다.

        Args:
            account_info: 계좌 정보 딕셔너리.
                필수 키: "margin_ratio" (float, 증거금 비율 %).

        Returns:
            True이면 정상 (100% 이상).
        """
        try:
            margin_ratio = account_info.get("margin_ratio", 0.0)

            if margin_ratio < REQUIRED_MARGIN_RATIO:
                logger.warning(
                    "증거금 비율 미달 | ratio=%.1f%% < %.1f%%",
                    margin_ratio, REQUIRED_MARGIN_RATIO,
                )
                return False

            logger.debug("증거금 비율 정상 | ratio=%.1f%%", margin_ratio)
            return True

        except Exception as exc:
            logger.error("증거금 비율 확인 에러 | error=%s", exc)
            return False

    async def validate_currency(self, order: dict) -> bool:
        """주문 통화가 USD인지 확인한다.

        KRW 주문 시도는 원천 차단한다.

        Args:
            order: 주문 정보 딕셔너리.
                선택 키: "currency" (기본값 "USD").

        Returns:
            True이면 USD 주문 (허용).
        """
        try:
            currency = order.get("currency", ALLOWED_CURRENCY).upper()

            if currency != ALLOWED_CURRENCY:
                logger.warning(
                    "비허용 통화 주문 시도 | currency=%s | allowed=%s",
                    currency, ALLOWED_CURRENCY,
                )
                return False

            return True

        except Exception as exc:
            logger.error("통화 검증 에러 | error=%s", exc)
            return False

    # ------------------------------------------------------------------
    # DB 기록
    # ------------------------------------------------------------------

    async def log_check(
        self, check_type: str, passed: bool, details: dict
    ) -> None:
        """자본금 검증 결과를 DB에 기록한다.

        Args:
            check_type: 검증 유형
                ("balance_validation", "margin_validation",
                 "currency_validation", "order_validation").
            passed: 검증 통과 여부.
            details: 상세 정보 딕셔너리.
        """
        try:
            async with get_session() as session:
                log_entry = CapitalGuardLog(
                    check_type=check_type,
                    passed=passed,
                    details=details,
                )
                session.add(log_entry)

            logger.debug(
                "CapitalGuard 로그 기록 | type=%s | passed=%s",
                check_type, passed,
            )
        except Exception as exc:
            logger.error(
                "CapitalGuard 로그 기록 실패 | type=%s | error=%s",
                check_type, exc,
            )
