"""BotHandler -- 텔레그램 봇 명령어를 수신하고 라우팅한다.

python-telegram-bot 라이브러리로 webhook/polling을 처리한다.
명령어를 CommandProcessor/TradeCommands로 위임한다.
"""
from __future__ import annotations

from typing import Any

from src.common.logger import get_logger
from src.telegram.command_processor import CommandProcessor
from src.telegram.message_formatter import MessageFormatter
from src.telegram.models import BotResponse
from src.telegram.permissions import Permissions
from src.telegram.trade_commands import TradeCommands

logger = get_logger(__name__)

try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
    )
    _HAS_TELEGRAM = True
except ImportError:
    _HAS_TELEGRAM = False
    logger.warning("python-telegram-bot 미설치, 봇 기능 비활성화")


class BotHandler:
    """텔레그램 봇 명령어 수신/라우팅 관리자이다."""

    def __init__(
        self,
        bot_token: str,
        permissions: Permissions,
        command_processor: CommandProcessor,
        trade_commands: TradeCommands,
        formatter: MessageFormatter,
    ) -> None:
        """의존성을 주입받아 초기화한다."""
        self._token = bot_token
        self._perms = permissions
        self._cmd = command_processor
        self._trade = trade_commands
        self._fmt = formatter
        self._app: object | None = None
        logger.info("BotHandler 초기화 완료")

    async def start(self) -> None:
        """봇 폴링을 시작한다."""
        if not _HAS_TELEGRAM:
            logger.error("python-telegram-bot 미설치, 봇 시작 불가")
            return

        self._app = Application.builder().token(self._token).build()
        app = self._app  # type: ignore[assignment]

        # 명령어 핸들러 등록
        app.add_handler(CommandHandler("start", self._on_command))
        app.add_handler(CommandHandler("status", self._on_command))
        app.add_handler(CommandHandler("positions", self._on_command))
        app.add_handler(CommandHandler("stop", self._on_command))
        app.add_handler(CommandHandler("help", self._on_command))
        app.add_handler(CommandHandler("buy", self._on_trade))
        app.add_handler(CommandHandler("sell", self._on_trade))

        await app.initialize()
        await app.start()
        logger.info("텔레그램 봇 시작 완료")

    async def stop(self) -> None:
        """봇을 정지한다."""
        if self._app is not None and _HAS_TELEGRAM:
            app = self._app  # type: ignore[assignment]
            await app.stop()
            await app.shutdown()
            logger.info("텔레그램 봇 정지 완료")

    async def _on_command(self, update: Any, context: Any) -> None:
        """일반 명령어 핸들러이다. 권한 확인 후 CommandProcessor로 위임한다."""
        if not _HAS_TELEGRAM:
            return
        upd: Update = update  # type: ignore[assignment]
        msg = upd.effective_message
        if msg is None:
            return

        user_id = upd.effective_user.id if upd.effective_user else 0
        chat_id = msg.chat_id
        perm = self._perms.check(user_id, chat_id)
        if not perm.allowed:
            await msg.reply_text(f"접근 거부: {perm.reason}")
            return

        command = (msg.text or "").split()[0]
        args = (msg.text or "").split()[1:]
        result = await self._cmd.process(command, args)
        response = BotResponse(reply_text=result.response_text)
        await msg.reply_text(response.reply_text, parse_mode=response.parse_mode)

    async def _on_trade(self, update: Any, context: Any) -> None:
        """매매 명령어 핸들러이다. /buy SOXL 5, /sell QLD 3 형식이다."""
        if not _HAS_TELEGRAM:
            return
        upd: Update = update  # type: ignore[assignment]
        msg = upd.effective_message
        if msg is None:
            return

        user_id = upd.effective_user.id if upd.effective_user else 0
        chat_id = msg.chat_id
        perm = self._perms.check(user_id, chat_id)
        if not perm.allowed:
            await msg.reply_text(f"접근 거부: {perm.reason}")
            return

        parts = (msg.text or "").split()
        if len(parts) < 3:
            await msg.reply_text("사용법: /buy TICKER QTY 또는 /sell TICKER QTY")
            return

        action = parts[0].strip("/").lower()
        ticker = parts[1].upper()
        try:
            quantity = int(parts[2])
        except ValueError:
            await msg.reply_text("수량은 정수여야 한다")
            return

        result = await self._trade.execute(
            {"action": action, "ticker": ticker, "quantity": quantity},
        )
        await msg.reply_text(result.message or ("실행 완료" if result.executed else "실행 실패"))
