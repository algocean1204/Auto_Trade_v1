"""
텔레그램 양방향 통신 핸들러.

User 1의 봇 토큰으로 polling 기반 메시지 수신을 실행하고,
명령과 자연어 메시지를 적절한 핸들러로 라우팅한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler as TGCommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.monitoring.telegram_notifier import TelegramNotifier
from src.telegram.commands import CommandHandler
from src.telegram.formatters import format_permission_denied, format_rate_limited
from src.telegram.nl_processor import NLProcessor
from src.telegram.permissions import (
    Permission,
    check_permission,
    check_rate_limit,
    get_user1_chat_id,
    get_user_label,
    is_known_user,
)
from src.telegram.trade_commands import TradeCommandManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramBotHandler:
    """텔레그램 양방향 통신을 관리하는 메인 핸들러 클래스이다.

    User 1의 봇 토큰을 사용하여 명령을 수신하고 처리한다.
    양쪽 사용자 모두 User 1의 봇에 명령을 보낼 수 있다.
    """

    def __init__(self, notifier: TelegramNotifier) -> None:
        """TelegramBotHandler를 초기화한다.

        Args:
            notifier: 기존 TelegramNotifier 인스턴스. 봇 토큰 공유용.
        """
        self._notifier = notifier
        self._command_handler = CommandHandler()
        self._trade_manager = TradeCommandManager()
        self._nl_processor = NLProcessor()
        self._application: Application | None = None
        self._running = False
        self._poll_task: asyncio.Task | None = None

        # User 1의 봇 토큰
        self._bot_token = self._get_primary_bot_token()

        if not self._bot_token:
            logger.warning(
                "TELEGRAM_BOT_TOKEN 미설정: 양방향 통신이 비활성화됩니다."
            )

    def _get_primary_bot_token(self) -> str:
        """User 1의 봇 토큰을 반환한다.

        Returns:
            봇 토큰 문자열. 미설정 시 빈 문자열.
        """
        return self._notifier.get_primary_bot_token()

    def set_trading_system(self, trading_system: Any) -> None:
        """TradingSystem 참조를 모든 하위 핸들러에 주입한다.

        Args:
            trading_system: TradingSystem 인스턴스.
        """
        self._command_handler.set_trading_system(trading_system)
        self._trade_manager.set_trading_system(trading_system)

        # Claude client를 NL 프로세서에 주입
        if trading_system.claude_client:
            self._nl_processor.set_claude_client(trading_system.claude_client)

        logger.info("TradingSystem 참조 주입 완료")

    async def start(self) -> None:
        """봇 polling을 백그라운드 태스크로 시작한다.

        Non-blocking으로 실행되어 트레이딩 루프와 병행한다.
        """
        if not self._bot_token:
            logger.warning("봇 토큰 미설정: polling 시작 불가")
            return

        try:
            logger.info("텔레그램 봇 핸들러 시작...")

            # Application 빌드
            self._application = (
                Application.builder()
                .token(self._bot_token)
                .build()
            )

            # 명령 핸들러 등록
            self._register_handlers()

            # Initialize and start polling
            await self._application.initialize()
            await self._application.start()
            await self._application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message"],
            )

            self._running = True
            logger.info("텔레그램 봇 polling 시작 완료")

        except Exception as exc:
            logger.error("텔레그램 봇 시작 실패: %s", exc)
            self._running = False

    async def stop(self) -> None:
        """봇 polling을 안전하게 종료한다."""
        if not self._running or self._application is None:
            return

        try:
            logger.info("텔레그램 봇 핸들러 종료 중...")
            self._running = False

            if self._application.updater and self._application.updater.running:
                await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()

            logger.info("텔레그램 봇 핸들러 종료 완료")
        except Exception as exc:
            logger.error("텔레그램 봇 종료 중 오류: %s", exc)

    def _register_handlers(self) -> None:
        """모든 명령 핸들러와 메시지 핸들러를 등록한다."""
        app = self._application

        # 읽기 명령
        app.add_handler(TGCommandHandler(["status", "s"], self._on_status))
        app.add_handler(TGCommandHandler(["positions", "p"], self._on_positions))
        app.add_handler(TGCommandHandler(["news", "n"], self._on_news))
        app.add_handler(TGCommandHandler(["analyze", "a"], self._on_analyze))
        app.add_handler(TGCommandHandler(["report", "r"], self._on_report))
        app.add_handler(TGCommandHandler(["balance", "b"], self._on_balance))
        app.add_handler(TGCommandHandler(["help", "h"], self._on_help))

        # 관리 명령
        app.add_handler(TGCommandHandler("stop", self._on_stop))
        app.add_handler(TGCommandHandler("resume", self._on_resume))
        app.add_handler(TGCommandHandler("buy", self._on_buy))
        app.add_handler(TGCommandHandler("sell", self._on_sell))
        app.add_handler(TGCommandHandler("confirm", self._on_confirm))
        app.add_handler(TGCommandHandler("cancel", self._on_cancel))

        # 자연어 메시지 (슬래시 명령이 아닌 모든 텍스트)
        app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self._on_text_message,
            )
        )

        logger.info("텔레그램 명령 핸들러 등록 완료")

    # ------------------------------------------------------------------
    # Middleware: 권한 + rate limit 체크
    # ------------------------------------------------------------------

    async def _pre_check(
        self,
        update: Update,
        required_permission: Permission,
    ) -> bool:
        """명령 실행 전 권한과 rate limit을 확인한다.

        Args:
            update: 텔레그램 Update 객체.
            required_permission: 필요한 권한 등급.

        Returns:
            통과 시 True. 실패 시 False (응답 메시지를 자동 발송한다).
        """
        if update.effective_chat is None or update.message is None:
            return False

        chat_id = update.effective_chat.id

        # 미등록 사용자: 무시 (응답 없음)
        if not is_known_user(chat_id):
            logger.warning("미등록 사용자 접근 시도: chat_id=%s", chat_id)
            return False

        # Rate limit 체크
        if not check_rate_limit(chat_id):
            msg = await format_rate_limited()
            await self._safe_reply(update, msg)
            return False

        # 권한 체크
        if not check_permission(chat_id, required_permission):
            msg = await format_permission_denied()
            await self._safe_reply(update, msg)
            return False

        return True

    async def _safe_reply(self, update: Update, text: str) -> None:
        """안전하게 메시지를 전송한다. Markdown 실패 시 plain text로 폴백한다.

        Args:
            update: 텔레그램 Update 객체.
            text: 발송할 텍스트.
        """
        if update.message is None:
            logger.warning("update.message가 None: 메시지 전송 불가")
            return
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as exc:
            logger.debug("Markdown 파싱 실패, plain text로 재시도: %s", exc)
            # Markdown 파싱 실패 시 plain text로 재시도
            try:
                await update.message.reply_text(text)
            except Exception as exc:
                logger.error("메시지 전송 완전 실패: %s", exc)

    # ------------------------------------------------------------------
    # 읽기 명령 핸들러
    # ------------------------------------------------------------------

    async def _on_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """시스템 상태를 조회한다."""
        if not await self._pre_check(update, Permission.READ):
            return
        user = get_user_label(update.effective_chat.id)
        logger.info("[%s] /status 명령 실행", user)
        response = await self._command_handler.handle_status()
        await self._safe_reply(update, response)

    async def _on_positions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """보유 포지션을 조회한다."""
        if not await self._pre_check(update, Permission.READ):
            return
        user = get_user_label(update.effective_chat.id)
        logger.info("[%s] /positions 명령 실행", user)
        response = await self._command_handler.handle_positions()
        await self._safe_reply(update, response)

    async def _on_news(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """최근 뉴스를 조회한다. 카테고리를 인자로 받을 수 있다."""
        if not await self._pre_check(update, Permission.READ):
            return

        user = get_user_label(update.effective_chat.id)
        category = None
        if context.args:
            category = context.args[0].lower()

        logger.info("[%s] /news 명령 실행 (category=%s)", user, category)
        response = await self._command_handler.handle_news(category=category)
        await self._safe_reply(update, response)

    async def _on_analyze(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """특정 종목을 분석한다."""
        if not await self._pre_check(update, Permission.READ):
            return

        user = get_user_label(update.effective_chat.id)

        if not context.args:
            await self._safe_reply(
                update,
                "\u26a0\ufe0f 분석할 티커를 지정하세요.\n"
                "사용법: /analyze SOXL 또는 /a QLD",
            )
            return

        ticker = context.args[0].upper()
        logger.info("[%s] /analyze %s 명령 실행", user, ticker)
        response = await self._command_handler.handle_analyze(ticker)
        await self._safe_reply(update, response)

    async def _on_report(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """일일 리포트를 조회한다."""
        if not await self._pre_check(update, Permission.READ):
            return
        user = get_user_label(update.effective_chat.id)
        logger.info("[%s] /report 명령 실행", user)
        response = await self._command_handler.handle_report()
        await self._safe_reply(update, response)

    async def _on_balance(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """계좌 잔고를 조회한다."""
        if not await self._pre_check(update, Permission.READ):
            return
        user = get_user_label(update.effective_chat.id)
        logger.info("[%s] /balance 명령 실행", user)
        response = await self._command_handler.handle_balance()
        await self._safe_reply(update, response)

    async def _on_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """도움말을 표시한다."""
        if not await self._pre_check(update, Permission.READ):
            return

        chat_id = update.effective_chat.id
        is_admin = check_permission(chat_id, Permission.CONTROL)
        user = get_user_label(chat_id)
        logger.info("[%s] /help 명령 실행", user)

        response = await self._command_handler.handle_help(is_admin=is_admin)
        await self._safe_reply(update, response)

    # ------------------------------------------------------------------
    # 관리 명령 핸들러 (User 1 전용)
    # ------------------------------------------------------------------

    async def _on_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """매매를 긴급 중단한다 (User 1 전용)."""
        if not await self._pre_check(update, Permission.CONTROL):
            return
        user = get_user_label(update.effective_chat.id)
        logger.info("[%s] /stop 명령 실행", user)
        response = await self._command_handler.handle_stop()
        await self._safe_reply(update, response)

    async def _on_resume(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """매매를 재개한다 (User 1 전용)."""
        if not await self._pre_check(update, Permission.CONTROL):
            return
        user = get_user_label(update.effective_chat.id)
        logger.info("[%s] /resume 명령 실행", user)
        response = await self._command_handler.handle_resume()
        await self._safe_reply(update, response)

    async def _on_buy(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """매수 주문을 생성한다 (User 1 전용).

        사용법: /buy SOXL 500 또는 /buy SOXL $500
        """
        if not await self._pre_check(update, Permission.TRADE):
            return

        user = get_user_label(update.effective_chat.id)

        if not context.args or len(context.args) < 2:
            await self._safe_reply(
                update,
                "\u26a0\ufe0f 사용법: /buy [티커] [금액]\n"
                "예: /buy SOXL 500 또는 /buy SOXL $1000",
            )
            return

        ticker = context.args[0].upper()
        amount = context.args[1]

        logger.info("[%s] /buy %s %s 명령 실행", user, ticker, amount)

        # 대기 주문 생성
        self._trade_manager.create_pending(
            chat_id=str(update.effective_chat.id),
            direction="buy",
            ticker=ticker,
            amount=amount,
        )

        from src.telegram.formatters import format_trade_confirmation
        msg = await format_trade_confirmation("buy", ticker, amount)
        await self._safe_reply(update, msg)

    async def _on_sell(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """매도 주문을 생성한다 (User 1 전용).

        사용법: /sell SOXL 500 또는 /sell SOXL all
        """
        if not await self._pre_check(update, Permission.TRADE):
            return

        user = get_user_label(update.effective_chat.id)

        if not context.args or len(context.args) < 2:
            await self._safe_reply(
                update,
                "\u26a0\ufe0f 사용법: /sell [티커] [금액|all]\n"
                "예: /sell SOXL 500 또는 /sell SOXL all",
            )
            return

        ticker = context.args[0].upper()
        amount = context.args[1]

        logger.info("[%s] /sell %s %s 명령 실행", user, ticker, amount)

        # 대기 주문 생성
        self._trade_manager.create_pending(
            chat_id=str(update.effective_chat.id),
            direction="sell",
            ticker=ticker,
            amount=amount,
        )

        from src.telegram.formatters import format_trade_confirmation
        msg = await format_trade_confirmation("sell", ticker, amount)
        await self._safe_reply(update, msg)

    async def _on_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """대기 중인 주문을 확인하고 실행한다 (User 1 전용)."""
        if not await self._pre_check(update, Permission.TRADE):
            return

        user = get_user_label(update.effective_chat.id)
        chat_id = str(update.effective_chat.id)

        logger.info("[%s] /confirm 명령 실행", user)

        result = await self._trade_manager.execute_pending(chat_id)
        await self._safe_reply(update, result["message"])

    async def _on_cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """대기 중인 주문을 취소한다 (User 1 전용)."""
        if not await self._pre_check(update, Permission.TRADE):
            return

        user = get_user_label(update.effective_chat.id)
        chat_id = str(update.effective_chat.id)

        logger.info("[%s] /cancel 명령 실행", user)

        cancelled = self._trade_manager.cancel_pending(chat_id)
        if cancelled:
            await self._safe_reply(update, "\u2705 대기 중인 주문이 취소되었습니다.")
        else:
            await self._safe_reply(update, "\u26a0\ufe0f 대기 중인 주문이 없습니다.")

    # ------------------------------------------------------------------
    # 자연어 메시지 핸들러
    # ------------------------------------------------------------------

    async def _on_text_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """슬래시 명령이 아닌 일반 텍스트 메시지를 처리한다.

        Claude Sonnet으로 의도를 분류하여 적절한 핸들러로 라우팅한다.
        """
        if update.effective_chat is None or update.message is None:
            return

        chat_id = update.effective_chat.id

        # 미등록 사용자: 무시
        if not is_known_user(chat_id):
            return

        # Rate limit
        if not check_rate_limit(chat_id):
            msg = await format_rate_limited()
            await self._safe_reply(update, msg)
            return

        text = update.message.text.strip()
        if not text:
            return

        user = get_user_label(chat_id)
        logger.info("[%s] 자연어 메시지: %s", user, text[:50])

        try:
            # 의도 분류
            intent_result = await self._nl_processor.classify_intent(text)
            intent = intent_result["intent"]
            params = intent_result.get("params", {})

            logger.info(
                "[%s] 의도 분류: %s (conf=%.2f)",
                user,
                intent,
                intent_result.get("confidence", 0),
            )

            # 의도에 따라 라우팅
            response = await self._route_intent(
                intent=intent,
                params=params,
                chat_id=chat_id,
                original_text=text,
            )

            await self._safe_reply(update, response)

        except Exception as exc:
            logger.error("[%s] 자연어 처리 실패: %s", user, exc)
            await self._safe_reply(
                update,
                "\u26a0\ufe0f 메시지 처리 중 오류가 발생했습니다.\n"
                "슬래시 명령어(/help)를 사용해 주세요.",
            )

    async def _route_intent(
        self,
        intent: str,
        params: dict[str, Any],
        chat_id: int | str,
        original_text: str,
    ) -> str:
        """분류된 의도를 적절한 핸들러로 라우팅한다.

        Args:
            intent: 분류된 의도 문자열.
            params: 의도 파라미터.
            chat_id: 텔레그램 chat ID.
            original_text: 원본 메시지 텍스트.

        Returns:
            응답 메시지 문자열.
        """
        # 읽기 명령
        if intent == "status":
            return await self._command_handler.handle_status()

        elif intent == "positions":
            return await self._command_handler.handle_positions()

        elif intent == "news":
            return await self._command_handler.handle_news()

        elif intent == "news_category":
            category = params.get("category")
            return await self._command_handler.handle_news(category=category)

        elif intent == "analyze":
            ticker = params.get("ticker")
            if not ticker:
                return "\u26a0\ufe0f 분석할 종목 티커를 말씀해 주세요. 예: SOXL 분석해줘"
            return await self._command_handler.handle_analyze(ticker.upper())

        elif intent == "report":
            return await self._command_handler.handle_report()

        elif intent == "balance":
            return await self._command_handler.handle_balance()

        elif intent == "help":
            is_admin = check_permission(chat_id, Permission.CONTROL)
            return await self._command_handler.handle_help(is_admin=is_admin)

        # 관리 명령 (User 1 전용)
        elif intent in ("buy", "sell"):
            if not check_permission(chat_id, Permission.TRADE):
                return await format_permission_denied()

            ticker = params.get("ticker")
            amount = params.get("amount", "100")
            if not ticker:
                return "\u26a0\ufe0f 종목 티커와 금액을 말씀해 주세요. 예: SOXL 500달러 매수"

            self._trade_manager.create_pending(
                chat_id=str(chat_id),
                direction=intent,
                ticker=ticker.upper(),
                amount=str(amount),
            )

            from src.telegram.formatters import format_trade_confirmation
            return await format_trade_confirmation(intent, ticker.upper(), str(amount))

        elif intent == "stop":
            if not check_permission(chat_id, Permission.CONTROL):
                return await format_permission_denied()
            return await self._command_handler.handle_stop()

        elif intent == "resume":
            if not check_permission(chat_id, Permission.CONTROL):
                return await format_permission_denied()
            return await self._command_handler.handle_resume()

        elif intent == "chat":
            # 일반 대화: Claude로 응답 생성
            return await self._nl_processor.generate_chat_response(original_text)

        else:
            return await self._nl_processor.generate_chat_response(original_text)
