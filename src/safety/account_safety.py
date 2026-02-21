"""
계좌 안전 3종 세트 모듈

매매 시작 전 반드시 확인해야 하는 3가지 항목:
    1. 통합증거금 미신청 확인
    2. 증거금 100% 확인
    3. KIS Open API 토큰 유효성 확인
"""

from datetime import datetime, timezone
from typing import Any

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
REQUIRED_MARGIN_RATIO: float = 100.0


class AccountSafetyChecker:
    """계좌 안전 3종 세트를 점검한다.

    통합증거금 미신청 상태, 증거금 100% 유지, KIS API 토큰 유효성을
    확인하여 매매 가능 여부를 판단한다.

    모든 public 메서드는 try/except로 감싸져 있어
    내부 에러가 시스템 크래시로 이어지지 않는다.

    Attributes:
        kis_client: KIS API 클라이언트 인스턴스 (선택적).
        unified_margin_enabled: 통합증거금 신청 여부 설정값.
    """

    def __init__(
        self,
        kis_client: Any = None,
        unified_margin_enabled: bool = False,
    ) -> None:
        """AccountSafetyChecker를 초기화한다.

        Args:
            kis_client: KISClient 인스턴스. None이면 설정값 기반으로만 확인한다.
            unified_margin_enabled: 통합증거금 신청 여부.
                False(미신청)여야 정상이다. True이면 위험 상태.
        """
        self.kis_client = kis_client
        self.unified_margin_enabled: bool = unified_margin_enabled
        logger.info(
            "AccountSafetyChecker 초기화 | kis_client=%s | unified_margin=%s",
            "연결됨" if kis_client is not None else "미연결",
            unified_margin_enabled,
        )

    # ------------------------------------------------------------------
    # 통합 점검
    # ------------------------------------------------------------------

    async def check_all(self) -> dict[str, Any]:
        """3종 전체 안전 점검을 수행한다.

        1. 통합증거금 미신청 확인
        2. 증거금 100% 확인
        3. KIS API 토큰 유효성 확인

        Returns:
            종합 점검 결과::

                {
                    "safe_to_trade": bool,
                    "checks": {
                        "unified_margin": {"ok": bool, "message": str},
                        "margin_ratio": {"ok": bool, "message": str},
                        "api_token": {"ok": bool, "message": str},
                    },
                    "issues": [str, ...],
                }
        """
        try:
            checks: dict[str, dict[str, Any]] = {}
            issues: list[str] = []

            # 1. 통합증거금 미신청 확인
            um_ok, um_msg = await self.check_unified_margin()
            checks["unified_margin"] = {"ok": um_ok, "message": um_msg}
            if not um_ok:
                issues.append(um_msg)

            # 2. 증거금 100% 확인
            mr_ok, mr_msg = await self.check_margin_ratio()
            checks["margin_ratio"] = {"ok": mr_ok, "message": mr_msg}
            if not mr_ok:
                issues.append(mr_msg)

            # 3. KIS API 토큰 유효성 확인
            tk_ok, tk_msg = await self.check_api_token()
            checks["api_token"] = {"ok": tk_ok, "message": tk_msg}
            if not tk_ok:
                issues.append(tk_msg)

            safe_to_trade = len(issues) == 0

            if safe_to_trade:
                logger.info("계좌 안전 3종 세트 점검 통과")
            else:
                logger.warning(
                    "계좌 안전 3종 세트 점검 실패 | issues=%s", issues,
                )

            return {
                "safe_to_trade": safe_to_trade,
                "checks": checks,
                "issues": issues,
            }

        except Exception as exc:
            logger.error("계좌 안전 3종 점검 중 에러 | error=%s", exc)
            return {
                "safe_to_trade": False,
                "checks": {},
                "issues": [f"점검 중 에러 발생: {exc}"],
            }

    # ------------------------------------------------------------------
    # 개별 점검
    # ------------------------------------------------------------------

    async def check_unified_margin(self) -> tuple[bool, str]:
        """통합증거금 미신청 상태인지 확인한다.

        통합증거금이 신청된 상태(True)이면 위험으로 판단한다.
        KIS API가 연결되어 있으면 API로 확인하고,
        미연결이면 설정값(unified_margin_enabled)으로 확인한다.

        Returns:
            (ok, message) 튜플.
            ok가 True이면 통합증거금 미신청 상태 (정상).
        """
        try:
            # KIS API가 연결되어 있으면 API로 확인 시도
            if self.kis_client is not None:
                try:
                    balance = await self.kis_client.get_balance()
                    # KIS API 잔고 조회가 성공하면 계좌 상태 정상으로 간주
                    # 통합증거금 상태는 별도 API가 필요하므로 설정값으로 보완
                    if self.unified_margin_enabled:
                        return (
                            False,
                            "통합증거금 신청 상태 감지: 미신청 상태로 변경 필요",
                        )
                    return True, "통합증거금 미신청 상태 (정상)"
                except Exception as api_exc:
                    logger.warning(
                        "KIS API로 통합증거금 확인 실패, 설정값 사용 | error=%s",
                        api_exc,
                    )

            # 설정값 기반 확인
            if self.unified_margin_enabled:
                return (
                    False,
                    "통합증거금 신청 상태: 미신청 상태로 변경 필요",
                )

            return True, "통합증거금 미신청 상태 (정상)"

        except Exception as exc:
            logger.error("통합증거금 확인 에러 | error=%s", exc)
            return False, f"통합증거금 확인 실패: {exc}"

    async def check_margin_ratio(self) -> tuple[bool, str]:
        """증거금 비율이 100% 이상인지 확인한다.

        100% 미만이면 신용/레버리지 거래 상태이므로 매매를 차단한다.
        KIS API가 연결되어 있으면 잔고 조회를 통해 확인하고,
        미연결이면 설정 기반으로 확인한다.

        Returns:
            (ok, message) 튜플.
            ok가 True이면 증거금 100% 이상 (정상).
        """
        try:
            if self.kis_client is not None:
                try:
                    balance = await self.kis_client.get_balance()
                    cash = balance.get("cash_balance", 0.0)
                    total_eval = balance.get("total_evaluation", 0.0)

                    # 포지션이 없으면 100%로 간주
                    if total_eval <= 0:
                        return True, "포지션 없음, 증거금 100% (정상)"

                    # 현금 / 총평가액 비율로 추정
                    # 실제 증거금 비율은 별도 API가 필요하지만 여기서는 근사치 사용
                    positions = balance.get("positions", [])
                    position_value = sum(
                        pos.get("quantity", 0) * pos.get("current_price", 0.0)
                        for pos in positions
                    )

                    if position_value > 0 and cash < 0:
                        return (
                            False,
                            f"증거금 비율 미달: 현금 ${cash:,.2f}, "
                            f"포지션 ${position_value:,.2f}",
                        )

                    return True, "증거금 100% 이상 (정상)"

                except Exception as api_exc:
                    logger.warning(
                        "KIS API로 증거금 확인 실패 | error=%s", api_exc,
                    )
                    return (
                        False,
                        f"증거금 확인을 위한 API 호출 실패: {api_exc}",
                    )

            # KIS 클라이언트 미연결 시 설정 기반
            settings = get_settings()
            if settings.trading_mode == "paper":
                return True, "모의 투자 모드: 증거금 100% 가정 (정상)"

            return (
                False,
                "실전 모드에서 KIS 클라이언트 미연결: 증거금 확인 불가",
            )

        except Exception as exc:
            logger.error("증거금 비율 확인 에러 | error=%s", exc)
            return False, f"증거금 비율 확인 실패: {exc}"

    async def check_api_token(self) -> tuple[bool, str]:
        """KIS Open API 토큰의 유효성을 확인한다.

        토큰이 만료되었거나 미설정 상태이면 매매를 차단한다.

        Returns:
            (ok, message) 튜플.
            ok가 True이면 토큰 유효 (정상).
        """
        try:
            settings = get_settings()

            # API 키 설정 확인
            if not settings.kis_app_key or not settings.kis_app_secret:
                return False, "KIS API 키 미설정"

            # KIS 클라이언트가 있으면 토큰 만료 확인
            if self.kis_client is not None:
                auth = getattr(self.kis_client, "auth", None)
                if auth is not None:
                    token = getattr(auth, "access_token", None)
                    token_expires = getattr(auth, "token_expires_at", None)

                    if token is None or token == "":
                        return False, "KIS API 토큰 미발급: 토큰 갱신 필요"

                    if token_expires is not None:
                        now = datetime.now(tz=timezone.utc)
                        if isinstance(token_expires, datetime):
                            if token_expires.tzinfo is None:
                                token_expires = token_expires.replace(
                                    tzinfo=timezone.utc
                                )
                            if now >= token_expires:
                                return (
                                    False,
                                    "KIS API 토큰 만료: 갱신 필요",
                                )

                    return True, "KIS API 토큰 유효 (정상)"

            # 클라이언트 미연결이지만 키는 설정됨
            if settings.trading_mode == "paper":
                return True, "모의 투자 모드: API 키 설정 확인됨 (정상)"

            return (
                False,
                "실전 모드에서 KIS 클라이언트 미연결: 토큰 확인 불가",
            )

        except Exception as exc:
            logger.error("API 토큰 확인 에러 | error=%s", exc)
            return False, f"API 토큰 확인 실패: {exc}"

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """현재 계좌 안전 상태 요약을 반환한다.

        Returns:
            상태 정보 딕셔너리.
        """
        return {
            "kis_client_connected": self.kis_client is not None,
            "unified_margin_enabled": self.unified_margin_enabled,
        }
