"""
TelegramGateway (C0.7) -- Telegram Bot API 메시지 발송 게이트웨이이다.

python-telegram-bot SDK 사용. 4096자 초과 시 자동 분할, 네트워크 실패 시 최대 3회 재시도.
connect=10s, read=15s, write=15s 타임아웃 적용.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_MAX_MSG_LEN: int = 4096
_MAX_RETRIES: int = 3
_RETRY_DELAY: float = 2.0
_CONNECT_TIMEOUT: float = 10.0
_READ_TIMEOUT: float = 15.0
_WRITE_TIMEOUT: float = 15.0
_instance: TelegramSender | None = None


class SendResult(BaseModel):
    """텔레그램 발송 결과이다."""
    success: bool
    message_id: int | None = None
    error: str | None = None


def _split_message(text: str, limit: int = _MAX_MSG_LEN) -> list[str]:
    """긴 메시지를 limit 이하 조각으로 줄바꿈 기준 분할한다."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            chunks.append(line[:limit])
            line = line[limit:]
        added = len(line) + (1 if current else 0)
        if current_len + added > limit:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += added
    if current:
        chunks.append("\n".join(current))
    return chunks


async def _retry(func: object, *args: object, **kwargs: object) -> object:
    """최대 _MAX_RETRIES회 재시도 후 전송을 수행한다."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await func(*args, **kwargs)  # type: ignore[operator]
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                logger.warning("텔레그램 전송 재시도 (%d/%d): %s", attempt + 1, _MAX_RETRIES + 1, exc)
                await asyncio.sleep(_RETRY_DELAY)
    raise last_exc  # type: ignore[misc]


class TelegramSender:
    """텔레그램 메시지 발송 클라이언트이다."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._chat_id = chat_id
        from telegram import Bot
        from telegram.request import HTTPXRequest
        request = HTTPXRequest(
            connect_timeout=_CONNECT_TIMEOUT,
            read_timeout=_READ_TIMEOUT,
            write_timeout=_WRITE_TIMEOUT,
        )
        self._bot = Bot(token=bot_token, request=request)
        logger.info(
            "TelegramSender 초기화 완료 (chat_id=%s, timeout=%.0f/%.0f/%.0fs)",
            chat_id, _CONNECT_TIMEOUT, _READ_TIMEOUT, _WRITE_TIMEOUT,
        )

    async def send_text(self, message: str, parse_mode: str = "HTML") -> SendResult:
        """텍스트 메시지를 발송한다. 4096자 초과 시 자동 분할한다."""
        chunks = _split_message(message)
        last_id: int | None = None
        for i, chunk in enumerate(chunks):
            try:
                sent = await _retry(
                    self._bot.send_message, chat_id=self._chat_id, text=chunk, parse_mode=parse_mode,
                )
                last_id = sent.message_id  # type: ignore[union-attr]
                logger.debug("텔레그램 발송 성공 (%d/%d, id=%s)", i + 1, len(chunks), last_id)
            except Exception as exc:
                logger.error("텔레그램 텍스트 발송 실패: %s", exc)
                return SendResult(success=False, error=str(exc))
        return SendResult(success=True, message_id=last_id)

    async def send_photo(self, photo_path: str, caption: str = "") -> SendResult:
        """이미지를 발송한다."""
        path = Path(photo_path)
        if not path.exists():
            msg = f"이미지 파일 없음: {photo_path}"
            logger.error(msg)
            return SendResult(success=False, error=msg)
        try:
            with open(path, "rb") as f:
                sent = await _retry(
                    self._bot.send_photo, chat_id=self._chat_id,
                    photo=f, caption=caption[:1024] if caption else None,
                )
            logger.debug("텔레그램 이미지 발송 성공 (id=%s)", sent.message_id)  # type: ignore[union-attr]
            return SendResult(success=True, message_id=sent.message_id)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("텔레그램 이미지 발송 실패: %s", exc)
            return SendResult(success=False, error=str(exc))

    async def close(self) -> None:
        """내부 httpx 세션을 정리한다."""
        if hasattr(self._bot, "shutdown"):
            try:
                await self._bot.shutdown()
            except Exception as exc:
                logger.warning("텔레그램 봇 shutdown 오류: %s", exc)
        logger.info("TelegramSender 종료 완료")


def get_telegram_sender(bot_token: str | None = None, chat_id: str | None = None) -> TelegramSender:
    """TelegramSender 싱글톤을 반환한다. 최초 호출 시 bot_token, chat_id 필수이다."""
    global _instance
    if _instance is not None:
        return _instance
    if not bot_token or not chat_id:
        raise ValueError("최초 호출 시 bot_token, chat_id 필수 (SecretVault에서 조회)")
    _instance = TelegramSender(bot_token=bot_token, chat_id=chat_id)
    return _instance


def reset_telegram_sender() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
