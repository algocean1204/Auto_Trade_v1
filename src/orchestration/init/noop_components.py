"""F9.1.1 NoOpComponents -- setup_mode 전용 더미 컴포넌트 모음이다.

첫 설치 시 API 키가 없는 환경에서 서버가 부팅 가능하도록
AiClient, BrokerClient, TelegramSender의 NoOp 구현을 제공한다.
실제 외부 호출을 수행하지 않으며, 최소 인터페이스만 구현한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.common.ai_gateway import AiClient, AiResponse
from src.common.broker_gateway import (
    BalanceData,
    BrokerClient,
    OHLCV,
    OrderRequest,
    OrderResult,
    PriceData,
)
from src.common.logger import get_logger
from src.common.telegram_gateway import SendResult, TelegramSender

logger = get_logger(__name__)


class _NoOpKisAuth:
    """setup_mode용 KisAuth 더미이다. 토큰 발급을 수행하지 않는다."""

    async def get_token(self) -> str:
        """토큰 발급 없이 빈 문자열을 반환한다."""
        logger.debug("NoOp KisAuth.get_token() 호출 (setup_mode)")
        return ""

    async def force_refresh(self) -> str:
        """강제 갱신 없이 빈 문자열을 반환한다."""
        logger.debug("NoOp KisAuth.force_refresh() 호출 (setup_mode)")
        return ""

    def invalidate_token(self) -> None:
        """무효화 동작을 건너뛴다."""


class NoOpBrokerClient(BrokerClient):
    """setup_mode용 BrokerClient 더미이다.

    preparation.py가 virtual_auth/real_auth를 직접 참조하므로
    NoOp KisAuth 인스턴스를 속성으로 노출한다.
    """

    def __init__(self) -> None:
        # BrokerClient.__init__은 KisAuth를 요구하므로 직접 속성을 설정한다.
        # super().__init__()을 호출하지 않는다 (외부 연결 없음).
        self.virtual_auth: _NoOpKisAuth = _NoOpKisAuth()  # type: ignore[assignment]
        self.real_auth: _NoOpKisAuth = _NoOpKisAuth()  # type: ignore[assignment]
        logger.info("NoOp BrokerClient 초기화 완료 (setup_mode)")

    async def get_price(self, ticker: str, exchange: str = "NAS") -> PriceData:
        """빈 가격 데이터를 반환한다."""
        return PriceData(
            ticker=ticker, price=0.0, change_pct=0.0,
            volume=0, timestamp=datetime.now(tz=timezone.utc),
        )

    async def get_balance(self) -> BalanceData:
        """빈 잔고 데이터를 반환한다."""
        return BalanceData(total_equity=0.0, available_cash=0.0, positions=[])

    async def place_order(self, order: OrderRequest) -> OrderResult:
        """주문을 실행하지 않고 rejected 결과를 반환한다."""
        return OrderResult(
            order_id="", status="rejected",
            message="setup_mode: 브로커 미연결",
        )

    async def cancel_order(self, order_id: str, exchange: str = "NAS") -> object:
        """취소 없이 실패 결과를 반환한다.

        CancelResult와 호환되는 간단한 객체를 반환한다.
        """
        from src.executor.broker.kis_api import CancelResult
        return CancelResult(success=False)

    async def get_exchange_rate(self) -> float:
        """환율 조회 없이 0.0을 반환한다."""
        return 0.0

    async def get_daily_candles(
        self, ticker: str, days: int = 30, exchange: str = "NAS",
    ) -> list[OHLCV]:
        """빈 캔들 리스트를 반환한다."""
        return []

    async def close(self) -> None:
        """정리할 리소스가 없다."""


class NoOpAiClient(AiClient):
    """setup_mode용 AiClient 더미이다.

    SDK/API 백엔드를 초기화하지 않으므로 실제 AI 호출이 발생하지 않는다.
    """

    def __init__(self) -> None:
        # AiClient.__init__은 SdkBackend()를 생성하므로 직접 속성만 설정한다.
        self._mode = "noop"
        self._api_key = ""
        self._sdk_backend = None  # type: ignore[assignment]
        self._api_backend = None
        # 동시 호출 제한 Semaphore는 유지한다 (외부 코드에서 참조할 수 있다)
        self._semaphores = {
            "opus": asyncio.Semaphore(4),
            "sonnet": asyncio.Semaphore(6),
            "haiku": asyncio.Semaphore(4),
        }
        logger.info("NoOp AiClient 초기화 완료 (setup_mode)")

    async def send_text(
        self,
        prompt: str,
        system: str = "",
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> AiResponse:
        """AI 호출 없이 빈 응답을 반환한다."""
        logger.debug("NoOp AiClient.send_text() 호출 (setup_mode)")
        return AiResponse(content="", model=model, source="sdk", confidence=0.0)

    async def local_classify(
        self, text: str, categories: list[str],
    ) -> tuple[str, float, str]:
        """로컬 LLM 분류 없이 기본값을 반환한다."""
        logger.debug("NoOp AiClient.local_classify() 호출 (setup_mode)")
        return (categories[0] if categories else "unknown", 0.0, "setup_mode")

    async def fast_local_classify(
        self, text: str, categories: list[str],
    ) -> tuple[str, float, str]:
        """빠른 로컬 분류 없이 기본값을 반환한다."""
        logger.debug("NoOp AiClient.fast_local_classify() 호출 (setup_mode)")
        return (categories[0] if categories else "unknown", 0.0, "setup_mode")

    async def local_translate(self, text: str, target_lang: str = "ko") -> str:
        """로컬 번역 없이 원본 텍스트를 반환한다."""
        logger.debug("NoOp AiClient.local_translate() 호출 (setup_mode)")
        return text

    def switch_backend(self, mode: str) -> None:
        """모드 전환을 건너뛴다."""
        logger.debug("NoOp AiClient.switch_backend(%s) 호출 (setup_mode)", mode)

    async def close(self) -> None:
        """정리할 리소스가 없다."""


class NoOpTelegramSender(TelegramSender):
    """setup_mode용 TelegramSender 더미이다.

    실제 텔레그램 Bot을 초기화하지 않으므로 네트워크 호출이 발생하지 않는다.
    """

    def __init__(self) -> None:
        # TelegramSender.__init__은 python-telegram-bot을 import하므로
        # super().__init__()을 호출하지 않고 최소 속성만 설정한다.
        self._recipients: list[tuple[str, str]] = []
        self._bots: dict[str, object] = {}
        logger.info("NoOp TelegramSender 초기화 완료 (setup_mode)")

    async def send_text(self, message: str, parse_mode: str = "HTML") -> SendResult:
        """전송 없이 로그만 출력하고 성공을 반환한다."""
        logger.info("NoOp TelegramSender.send_text() 호출 (setup_mode): %s", message[:80])
        return SendResult(success=True, message_id=None)

    async def send_photo(
        self, photo_path: str, caption: str = "", parse_mode: str = "HTML",
    ) -> SendResult:
        """전송 없이 성공을 반환한다."""
        logger.debug("NoOp TelegramSender.send_photo() 호출 (setup_mode)")
        return SendResult(success=True, message_id=None)

    async def close(self) -> None:
        """정리할 리소스가 없다."""
