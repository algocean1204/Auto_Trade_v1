"""
TelegramGateway (C0.7) -- Telegram Bot API 메시지 발송 게이트웨이이다.

python-telegram-bot SDK 사용. 4096자 초과 시 자동 분할, 네트워크 실패 시 최대 3회 재시도.
connect=10s, read=15s, write=15s 타임아웃 적용.
다중 수신자(최대 5명)를 지원하며, 수신자마다 서로 다른 봇 토큰 사용이 가능하다.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

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

# Telegram HTML 모드에서 허용하는 태그 패턴 (열기/닫기)
_HTML_TAG_RE = re.compile(r"</?(?:b|i|u|s|code|pre|a)[^>]*>", re.IGNORECASE)


def escape_html(text: str) -> str:
    """텔레그램 HTML 특수문자(&, <, >)를 이스케이프한다.

    사용자/외부 데이터를 HTML 메시지에 삽입할 때 반드시 호출해야 한다.
    이미 HTML 마크업이 포함된 텍스트에는 사용하지 않는다.
    """
    return html.escape(text, quote=False)


class SendResult(BaseModel):
    """텔레그램 발송 결과이다."""
    success: bool
    message_id: int | None = None
    error: str | None = None


def _close_open_tags(chunk: str) -> str:
    """청크 내에서 열린 채 닫히지 않은 HTML 태그를 닫는다.

    Telegram은 <b>, <i>, <u>, <s>, <code>, <pre>, <a> 태그를 지원한다.
    분할 시 열린 태그가 닫히지 않으면 파싱 오류가 발생하므로 자동으로 닫아준다.
    """
    open_tags: list[str] = []
    for m in _HTML_TAG_RE.finditer(chunk):
        tag_str = m.group()
        if tag_str.startswith("</"):
            # 닫기 태그 — 가장 최근에 열린 동일 태그를 제거한다
            tag_name = tag_str[2:].rstrip(">").strip().lower()
            for i in range(len(open_tags) - 1, -1, -1):
                if open_tags[i] == tag_name:
                    open_tags.pop(i)
                    break
        else:
            # 열기 태그 — 태그 이름만 추출한다
            inner = tag_str[1:].rstrip(">").strip().split()[0].lower()
            open_tags.append(inner)
    # 역순으로 닫기 태그를 추가한다
    for tag_name in reversed(open_tags):
        chunk += f"</{tag_name}>"
    return chunk


def _reopen_tags(prev_chunk: str) -> str:
    """이전 청크에서 닫힌 태그를 다음 청크 앞에 다시 여는 접두어를 반환한다."""
    open_tags: list[tuple[str, str]] = []  # (태그명, 전체 열기 태그)
    for m in _HTML_TAG_RE.finditer(prev_chunk):
        tag_str = m.group()
        if tag_str.startswith("</"):
            tag_name = tag_str[2:].rstrip(">").strip().lower()
            for i in range(len(open_tags) - 1, -1, -1):
                if open_tags[i][0] == tag_name:
                    open_tags.pop(i)
                    break
        else:
            inner = tag_str[1:].rstrip(">").strip().split()[0].lower()
            open_tags.append((inner, tag_str))
    return "".join(full for _, full in open_tags)


def _split_message(text: str, limit: int = _MAX_MSG_LEN) -> list[str]:
    """긴 메시지를 limit 이하 조각으로 줄바꿈 기준 분할한다.

    HTML 태그가 청크 경계에서 잘리지 않도록 열린 태그를 자동 닫고,
    다음 청크에서 다시 열어준다.
    """
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

    # HTML 태그 안전성 보정: 각 청크에서 열린 태그를 닫고 다음 청크에서 다시 연다
    safe_chunks: list[str] = []
    for i, chunk in enumerate(chunks):
        if i > 0 and safe_chunks:
            # 이전 청크 원본에서 열려 있던 태그를 이 청크 앞에 다시 연다
            prefix = _reopen_tags(chunks[i - 1])
            if prefix:
                chunk = prefix + chunk
        safe_chunks.append(_close_open_tags(chunk))
    return safe_chunks


async def _retry(func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
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


def _make_bot(bot_token: str) -> Any:
    """Bot 인스턴스를 생성한다. 공통 타임아웃 설정을 적용한다."""
    from telegram import Bot
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(
        connect_timeout=_CONNECT_TIMEOUT,
        read_timeout=_READ_TIMEOUT,
        write_timeout=_WRITE_TIMEOUT,
    )
    return Bot(token=bot_token, request=request)


class TelegramSender:
    """다중 수신자를 지원하는 텔레그램 메시지 발송 클라이언트이다."""

    def __init__(
        self,
        recipients: list[tuple[str, str]] | None = None,
        *,
        bot_token: str = "",
        chat_id: str = "",
    ) -> None:
        # 하위 호환: 단일 token/chat_id → recipients 리스트로 변환한다
        if recipients:
            self._recipients = [(t, c) for t, c in recipients if t and c]
        elif bot_token and chat_id:
            self._recipients = [(bot_token, chat_id)]
        else:
            self._recipients = []
        # 수신자별 Bot 인스턴스를 캐싱한다 (동일 토큰은 재사용)
        self._bots: dict[str, Any] = {}
        for token, _ in self._recipients:
            if token not in self._bots:
                self._bots[token] = _make_bot(token)
        logger.info(
            "TelegramSender 초기화 완료 (수신자=%d명, timeout=%.0f/%.0f/%.0fs)",
            len(self._recipients), _CONNECT_TIMEOUT, _READ_TIMEOUT, _WRITE_TIMEOUT,
        )

    async def send_text(self, message: str, parse_mode: str = "HTML") -> SendResult:
        """모든 수신자에게 텍스트 메시지를 발송한다. 개별 실패는 로그만 남긴다."""
        chunks = _split_message(message)
        last_id: int | None = None
        any_success = False
        for bot_token, chat_id in self._recipients:
            bot = self._bots[bot_token]
            for i, chunk in enumerate(chunks):
                try:
                    sent = await _retry(
                        bot.send_message,  # type: ignore[union-attr]
                        chat_id=chat_id, text=chunk, parse_mode=parse_mode,
                    )
                    last_id = sent.message_id  # type: ignore[union-attr]
                    any_success = True
                    logger.debug("텔레그램 발송 성공 (chat_id=%s, %d/%d)", chat_id, i + 1, len(chunks))
                except Exception as exc:
                    logger.warning("텔레그램 텍스트 발송 실패 (chat_id=%s): %s", chat_id, exc)
                    break  # 이 수신자의 나머지 청크는 건너뛴다
        if not any_success and self._recipients:
            return SendResult(success=False, error="모든 수신자 전송 실패")
        return SendResult(success=True, message_id=last_id)

    async def send_photo(
        self, photo_path: str, caption: str = "", parse_mode: str = "HTML",
    ) -> SendResult:
        """모든 수신자에게 이미지를 발송한다. 개별 실패는 로그만 남긴다."""
        path = Path(photo_path)
        if not path.exists():
            msg = f"이미지 파일 없음: {photo_path}"
            logger.error(msg)
            return SendResult(success=False, error=msg)
        any_success = False
        last_id: int | None = None
        # 파일을 바이트로 한 번 읽어 재시도 시 파일 핸들 위치 문제를 방지한다
        photo_bytes = path.read_bytes()
        for bot_token, chat_id in self._recipients:
            bot = self._bots[bot_token]
            try:
                sent = await _retry(
                    bot.send_photo,  # type: ignore[union-attr]
                    chat_id=chat_id, photo=photo_bytes,
                    caption=caption[:1024] if caption else None,
                    parse_mode=parse_mode if caption else None,
                )
                last_id = sent.message_id  # type: ignore[union-attr]
                any_success = True
                logger.debug("텔레그램 이미지 발송 성공 (chat_id=%s)", chat_id)
            except Exception as exc:
                logger.warning("텔레그램 이미지 발송 실패 (chat_id=%s): %s", chat_id, exc)
        if not any_success and self._recipients:
            return SendResult(success=False, error="모든 수신자 이미지 전송 실패")
        return SendResult(success=True, message_id=last_id)

    async def close(self) -> None:
        """내부 httpx 세션을 정리한다."""
        for bot in self._bots.values():
            if hasattr(bot, "shutdown"):
                try:
                    await bot.shutdown()  # type: ignore[union-attr]
                except Exception as exc:
                    logger.warning("텔레그램 봇 shutdown 오류: %s", exc)
        logger.info("TelegramSender 종료 완료")


def get_telegram_sender(
    recipients: list[tuple[str, str]] | None = None,
    *,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> TelegramSender:
    """TelegramSender 싱글톤을 반환한다. 최초 호출 시 수신자 정보가 필수이다."""
    global _instance
    if _instance is not None:
        return _instance
    # 하위 호환: 단일 token/chat_id가 전달되면 recipients로 변환한다
    if not recipients and bot_token and chat_id:
        recipients = [(bot_token, chat_id)]
    if not recipients:
        raise ValueError("최초 호출 시 recipients 또는 bot_token+chat_id 필수")
    _instance = TelegramSender(recipients=recipients)
    return _instance


def reset_telegram_sender() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
