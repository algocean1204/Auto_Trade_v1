"""
매매 전 안전 점검 통합 모듈
QuotaGuard + HardSafety를 통합하여 단일 인터페이스를 제공한다.

사용 흐름:
    1. pre_session_check() -> 세션 시작 전 시스템 점검
    2. pre_trade_check() -> 매매 전 종합 안전 점검
    3. get_safety_status() -> 대시보드용 현재 안전 상태
"""

from typing import Any

from src.safety.hard_safety import HardSafety
from src.safety.quota_guard import QuotaGuard
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SafetyChecker:
    """QuotaGuard와 HardSafety를 통합하여 단일 안전 점검 인터페이스를 제공한다.

    모든 매매 행위 전에 이 클래스의 pre_trade_check()를 호출하여
    Quota, VIX, 포지션 한도, 일일 거래 한도, 일일 손실 한도를
    종합적으로 검증해야 한다.

    Attributes:
        quota: QuotaGuard 인스턴스.
        safety: HardSafety 인스턴스.
    """

    def __init__(self, quota_guard: QuotaGuard, hard_safety: HardSafety) -> None:
        """SafetyChecker를 초기화한다.

        Args:
            quota_guard: QuotaGuard 인스턴스.
            hard_safety: HardSafety 인스턴스.
        """
        self.quota: QuotaGuard = quota_guard
        self.safety: HardSafety = hard_safety
        logger.info("SafetyChecker 초기화 완료")

    async def pre_trade_check(
        self,
        order: dict[str, Any],
        portfolio: dict[str, Any],
        vix: float,
    ) -> dict[str, Any]:
        """매매 전 종합 안전 점검을 수행한다.

        Quota, VIX, 포지션 한도, 일일 거래 한도, 일일 손실 한도를
        모두 확인하고 결과를 반환한다.

        Args:
            order: 주문 정보 딕셔너리.
                필수 키: "ticker", "side", "quantity", "price".
            portfolio: 포트폴리오 정보 딕셔너리.
                필수 키: "positions", "cash", "total_value".
            vix: 현재 VIX 지수 값.

        Returns:
            종합 점검 결과 딕셔너리:
            {
                "allowed": bool,
                "checks": {
                    "quota": {"ok": bool, "remaining": int, "usage_pct": float},
                    "vix": {"ok": bool, "current": float, "threshold": int},
                    "position_limit": {"ok": bool, "reason": str},
                    "daily_limit": {"ok": bool, "trades_remaining": int},
                    "daily_loss": {"ok": bool, "current_loss": float},
                },
                "block_reason": str or None,
            }
        """
        checks: dict[str, Any] = {}
        block_reason: str | None = None

        # 1. Quota 확인
        quota_remaining = self.quota.get_remaining()
        quota_usage_pct = self.quota.get_usage_pct()
        quota_ok = self.quota.can_call()
        checks["quota"] = {
            "ok": quota_ok,
            "remaining": quota_remaining,
            "usage_pct": round(quota_usage_pct, 1),
        }
        if not quota_ok:
            block_reason = f"Quota 소진: 사용률 {quota_usage_pct:.1f}%, 잔여 {quota_remaining}회"

        # 2. VIX 확인
        vix_ok = self.safety.check_vix(vix)
        checks["vix"] = {
            "ok": vix_ok,
            "current": round(vix, 1),
            "threshold": self.safety.vix_shutdown_threshold,
        }
        if not vix_ok and block_reason is None:
            block_reason = f"VIX 매매 중단: {vix:.1f} >= {self.safety.vix_shutdown_threshold}"

        # 3. 포지션 한도 확인 (HardSafety.check_new_order)
        position_ok, position_reason = self.safety.check_new_order(order, portfolio)
        checks["position_limit"] = {
            "ok": position_ok,
            "reason": position_reason,
        }
        if not position_ok and block_reason is None:
            block_reason = position_reason

        # 4. 일일 거래 한도 확인
        trades_remaining = self.safety.max_daily_trades - self.safety.daily_trades
        daily_limit_ok = trades_remaining > 0
        checks["daily_limit"] = {
            "ok": daily_limit_ok,
            "trades_remaining": max(trades_remaining, 0),
        }
        if not daily_limit_ok and block_reason is None:
            block_reason = f"일일 거래 한도 초과: {self.safety.daily_trades}/{self.safety.max_daily_trades}"

        # 5. 일일 손실 한도 확인
        daily_loss_ok = not self.safety.is_shutdown
        checks["daily_loss"] = {
            "ok": daily_loss_ok,
            "current_loss": round(self.safety.daily_pnl_pct, 2),
        }
        if not daily_loss_ok and block_reason is None:
            block_reason = (
                f"일일 손실 한도 도달: {self.safety.daily_pnl_pct:.2f}% "
                f"<= {self.safety.max_daily_loss_pct:.1f}%"
            )

        # 종합 판단: 매도 주문이 아닌 경우 모든 체크가 통과해야 함
        side = order.get("side", "").lower()
        if side == "sell":
            # 매도(청산)는 안전 규칙과 무관하게 허용
            allowed = True
            block_reason = None
        else:
            allowed = all(
                check.get("ok", False) for check in checks.values()
            )

        result = {
            "allowed": allowed,
            "checks": checks,
            "block_reason": block_reason,
        }

        if not allowed:
            logger.warning(
                "매매 전 안전 점검 실패 | ticker=%s | reason=%s",
                order.get("ticker"),
                block_reason,
            )
        else:
            logger.debug(
                "매매 전 안전 점검 통과 | ticker=%s | side=%s",
                order.get("ticker"),
                side,
            )

        return result

    async def pre_session_check(self) -> dict[str, Any]:
        """세션 시작 전 시스템 점검을 수행한다.

        Claude API, KIS API, DB 연결 상태와 Quota 잔여량을 확인한다.

        Returns:
            {"safe_to_trade": bool, "issues": [str, ...], "details": {...}}
        """
        issues: list[str] = []
        details: dict[str, Any] = {}

        # 1. Claude API 연결 확인 (ping)
        try:
            await self.quota.claude_client.call(
                prompt="ping",
                task_type="news_classification",
                max_tokens=10,
            )
            details["claude_api"] = {"ok": True}
            self.quota.record_call()
            logger.info("세션 점검: Claude API 연결 정상")
        except Exception as e:
            details["claude_api"] = {"ok": False, "error": str(e)}
            issues.append(f"Claude API 연결 실패: {e}")
            logger.error("세션 점검: Claude API 연결 실패 | %s", e)

        # 2. KIS API 연결 확인
        # KIS 클라이언트는 아직 통합되지 않았으므로 설정 존재 여부로 확인
        settings = get_settings()
        if settings.kis_app_key and settings.kis_app_secret:
            details["kis_api"] = {"ok": True, "mode": settings.trading_mode}
            logger.info("세션 점검: KIS API 설정 확인 (mode=%s)", settings.trading_mode)
        else:
            details["kis_api"] = {"ok": False, "error": "KIS API 키 미설정"}
            issues.append("KIS API 키가 설정되지 않음")
            logger.warning("세션 점검: KIS API 키 미설정")

        # 3. DB 연결 확인
        # DB 세션은 아직 통합되지 않았으므로 설정 존재 여부로 확인
        if settings.db_host and settings.db_name:
            details["database"] = {"ok": True, "host": settings.db_host}
            logger.info("세션 점검: DB 설정 확인 (host=%s)", settings.db_host)
        else:
            details["database"] = {"ok": False, "error": "DB 설정 미완료"}
            issues.append("DB 설정이 완료되지 않음")
            logger.warning("세션 점검: DB 설정 미완료")

        # 4. Quota 잔여량 확인
        quota_remaining = self.quota.get_remaining()
        quota_usage_pct = self.quota.get_usage_pct()
        details["quota"] = {
            "ok": self.quota.can_call(),
            "remaining": quota_remaining,
            "usage_pct": round(quota_usage_pct, 1),
        }
        if not self.quota.can_call():
            issues.append(
                f"Quota 부족: 잔여 {quota_remaining}회 (사용률 {quota_usage_pct:.1f}%)"
            )
            logger.warning("세션 점검: Quota 부족")

        safe_to_trade = len(issues) == 0

        if safe_to_trade:
            logger.info("세션 점검 완료: 매매 가능 상태")
        else:
            logger.warning("세션 점검 완료: 매매 불가 | issues=%s", issues)

        return {
            "safe_to_trade": safe_to_trade,
            "issues": issues,
            "details": details,
        }

    def get_safety_status(self) -> dict[str, Any]:
        """현재 안전 상태 요약을 반환한다 (대시보드용).

        Returns:
            안전 상태 요약 딕셔너리.
        """
        quota_status = self.quota.get_status()
        safety_status = self.safety.get_status()

        # 전체 안전 등급 산출
        if safety_status["is_shutdown"]:
            grade = "SHUTDOWN"
        elif not quota_status["can_call"]:
            grade = "QUOTA_EXHAUSTED"
        elif quota_status["usage_pct"] >= 75.0:
            grade = "WARNING"
        elif safety_status["daily_trades"] >= safety_status["max_daily_trades"] * 0.8:
            grade = "WARNING"
        else:
            grade = "NORMAL"

        return {
            "grade": grade,
            "quota": quota_status,
            "hard_safety": safety_status,
        }
