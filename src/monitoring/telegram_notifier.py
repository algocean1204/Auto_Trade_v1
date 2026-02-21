"""
Telegram Bot 기반 알림 시스템.

등급별(CRITICAL/WARNING/INFO) 메시지를 다중 수신자에게 Telegram으로 발송하고
notification_log 테이블에 기록한다. Bot 미설정 시 graceful degradation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.db.connection import get_session
from src.db.models import NotificationLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 등급별 이모지 프리픽스
_SEVERITY_PREFIX = {
    "critical": "\U0001f534",  # red circle
    "warning": "\U0001f7e1",   # yellow circle
    "info": "\U0001f7e2",      # green circle
}

_CHANNEL = "telegram"


@dataclass
class _Recipient:
    """텔레그램 수신자 정보를 관리하는 데이터 클래스이다."""

    token: str
    chat_id: str
    bot: Any = field(default=None, repr=False)
    enabled: bool = True


class TelegramNotifier:
    """Telegram Bot을 통한 다중 수신자 알림 발송 클래스.

    환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (1번 수신자) 및
    TELEGRAM_BOT_TOKEN_2, TELEGRAM_CHAT_ID_2 (2번 수신자, optional)를 사용한다.
    수신자가 하나도 설정되지 않으면 메시지를 로그로만 남기고
    에러를 발생시키지 않는다 (graceful degradation).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._recipients: list[_Recipient] = []

        # 1번 수신자
        if settings.telegram_bot_token and settings.telegram_chat_id:
            self._recipients.append(
                _Recipient(
                    token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                )
            )

        # 2번 수신자 (optional)
        if settings.telegram_bot_token_2 and settings.telegram_chat_id_2:
            self._recipients.append(
                _Recipient(
                    token=settings.telegram_bot_token_2,
                    chat_id=settings.telegram_chat_id_2,
                )
            )

        self._enabled: bool = len(self._recipients) > 0

        if not self._enabled:
            logger.warning("Telegram 알림 비활성화: 수신자 미설정")
        else:
            logger.info(
                "Telegram 알림 활성화: %d명 수신자", len(self._recipients)
            )

    async def _get_bot(self, recipient: _Recipient) -> Any:
        """수신자별 Bot 인스턴스를 lazy-init으로 반환한다."""
        if recipient.bot is None and recipient.enabled:
            try:
                from telegram import Bot

                recipient.bot = Bot(token=recipient.token)
            except ImportError:
                logger.error(
                    "python-telegram-bot 패키지 미설치. pip install python-telegram-bot"
                )
                recipient.enabled = False
            except Exception as exc:
                logger.error(
                    "Telegram Bot 초기화 실패 (chat_id=%s): %s",
                    recipient.chat_id,
                    exc,
                )
                recipient.enabled = False
        return recipient.bot

    async def _send_to_recipient(
        self, recipient: _Recipient, text: str
    ) -> bool:
        """단일 수신자에게 메시지를 발송한다."""
        try:
            bot = await self._get_bot(recipient)
            if bot is not None:
                await bot.send_message(
                    chat_id=recipient.chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                return True
        except Exception as exc:
            logger.error(
                "Telegram 발송 실패 (chat_id=%s): %s",
                recipient.chat_id,
                exc,
            )
        return False

    # ------------------------------------------------------------------
    # 메시지 발송
    # ------------------------------------------------------------------

    async def send_message(
        self,
        title: str,
        message: str,
        severity: str = "info",
    ) -> bool:
        """메시지를 모든 수신자에게 발송하고 DB에 기록한다.

        Args:
            title: 메시지 제목.
            message: 메시지 본문.
            severity: 등급 ("critical", "warning", "info").

        Returns:
            발송 성공 여부 (하나 이상의 수신자에게 성공하면 True).
        """
        severity = severity.lower()
        prefix = _SEVERITY_PREFIX.get(severity, _SEVERITY_PREFIX["info"])
        full_message = f"{prefix} *{title}*\n\n{message}"

        delivered = False

        if self._enabled:
            active = [r for r in self._recipients if r.enabled]
            if active:
                results = await asyncio.gather(
                    *[
                        self._send_to_recipient(r, full_message)
                        for r in active
                    ],
                    return_exceptions=True,
                )
                delivered = any(r is True for r in results)

                success_count = sum(1 for r in results if r is True)
                logger.info(
                    "Telegram 메시지 발송 | severity=%s | title=%s | %d/%d 성공",
                    severity,
                    title,
                    success_count,
                    len(active),
                )
        else:
            logger.info(
                "Telegram 비활성 상태 - 로그 전용 | severity=%s | title=%s | message=%s",
                severity,
                title,
                message,
            )

        # DB 기록 (한 번만)
        await self._log_notification(
            severity=severity,
            title=title,
            message=message,
            delivered=delivered,
        )

        return delivered

    # ------------------------------------------------------------------
    # 편의 메서드
    # ------------------------------------------------------------------

    @staticmethod
    def build_trade_reasoning_summary(decision: dict[str, Any]) -> str:
        """AI 매매 결정으로부터 3줄 한국어 요약을 생성한다.

        decision 딕셔너리의 주요 필드(reason, confidence, market_regime,
        stop_loss_pct, take_profit_pct, time_horizon, ai_signals)를 활용하여
        매매 근거를 3줄로 압축한다. 필드 누락 시 fallback 텍스트를 사용한다.

        Args:
            decision: AI 매매 결정 딕셔너리.
                주요 키: reason, confidence, market_regime, stop_loss_pct,
                         take_profit_pct, time_horizon, ai_signals (optional).

        Returns:
            3줄 요약 문자열 (줄바꿈 포함).
        """
        try:
            regime = decision.get("market_regime") or decision.get("regime", "")
            confidence = decision.get("confidence", 0.0)
            reason = decision.get("reason", "")
            stop_loss_pct = decision.get("stop_loss_pct", 0.0)
            take_profit_pct = decision.get("take_profit_pct", 0.0)
            time_horizon = decision.get("time_horizon", "")
            ai_signals: list[dict[str, Any]] = decision.get("ai_signals", [])

            # Line 1: 시장 레짐 + 핵심 매크로 요인
            regime_display_map = {
                "strong_bull": "강세장",
                "mild_bull": "완만한 강세",
                "sideways": "횡보장",
                "mild_bear": "약세장",
                "crash": "급락 국면",
            }
            regime_kr = regime_display_map.get(regime, regime) if regime else "시장 상황 미확인"

            # ai_signals에서 매크로 관련 시그널 추출
            macro_signal = ""
            for sig in ai_signals:
                sig_reason = sig.get("reason", "")
                if any(kw in sig_reason for kw in ["VIX", "금리", "매크로", "Fed", "FOMC", "CPI", "달러"]):
                    macro_signal = sig_reason[:30]
                    break

            if macro_signal:
                line1 = f"1. {regime_kr} 국면, {macro_signal}"
            elif regime_kr:
                line1 = f"1. {regime_kr} 국면"
            else:
                line1 = "1. 시장 상황 분석 완료"

            # Line 2: 핵심 시그널/촉매 (reason 첫 문장 또는 ai_signals의 가장 임팩트 있는 시그널)
            core_signal = ""
            if reason:
                # reason의 첫 문장만 추출
                first_sentence = reason.split(".")[0].strip()
                core_signal = first_sentence[:60] if first_sentence else ""
            if not core_signal and ai_signals:
                core_signal = ai_signals[0].get("reason", "")[:60]
            if not core_signal:
                core_signal = "핵심 시그널 기반 진입"

            line2 = f"2. {core_signal}"

            # Line 3: 신뢰도 + 리스크/수익 비율
            confidence_pct = int(confidence * 100) if isinstance(confidence, float) else int(confidence)
            risk_reward_parts = []
            if stop_loss_pct:
                risk_reward_parts.append(f"손절 -{stop_loss_pct:.1f}%")
            if take_profit_pct:
                risk_reward_parts.append(f"익절 +{take_profit_pct:.1f}%")
            if time_horizon:
                horizon_map = {"intraday": "당일", "swing": "스윙", "overnight": "야간"}
                risk_reward_parts.append(horizon_map.get(time_horizon, time_horizon))

            if risk_reward_parts:
                line3 = f"3. 신뢰도 {confidence_pct}%, {' / '.join(risk_reward_parts)}"
            else:
                line3 = f"3. 신뢰도 {confidence_pct}%"

            return f"{line1}\n{line2}\n{line3}"

        except Exception as exc:
            logger.warning("매매 근거 요약 생성 실패 (fallback 사용): %s", exc)
            return "1. 시장 분석 완료\n2. AI 시그널 기반 진입\n3. 리스크 관리 적용"

    async def send_trade_notification(
        self,
        trade: dict[str, Any],
        decision: dict[str, Any] | None = None,
    ) -> bool:
        """매매 체결 알림을 발송한다.

        trade에 체결 정보를 포함하고, decision이 제공되면 AI 3줄 매매 근거 요약을
        함께 전송한다. decision 미제공 시 기존 형식으로 발송한다.

        Args:
            trade: 매매 체결 정보 딕셔너리.
                keys: ticker, direction, side, price, quantity, pnl_pct (optional).
            decision: AI 매매 결정 딕셔너리 (optional).
                keys: reason, confidence, market_regime, stop_loss_pct,
                      take_profit_pct, time_horizon, ai_signals.

        Returns:
            발송 성공 여부.
        """
        ticker = trade.get("ticker", "N/A")
        # side(buy/sell) 또는 direction 필드 통합 처리
        side = trade.get("side") or trade.get("direction", "N/A")
        price = trade.get("price", 0.0) or 0.0
        quantity = trade.get("quantity", 0) or 0
        pnl_pct = trade.get("pnl_pct")

        action_kr = "매수" if side in ("buy", "long") else "매도" if side in ("sell", "short") else side.upper()
        amount = price * quantity

        lines: list[str] = [
            f"${price:.2f} x {quantity}주 (${amount:,.2f})",
        ]
        if pnl_pct is not None:
            lines.append(f"손익: {pnl_pct:+.2f}%")

        if decision:
            reasoning = self.build_trade_reasoning_summary(decision)
            lines.append("")
            lines.append("매매 근거 (3줄 요약):")
            lines.append(reasoning)

        severity = "info"
        if pnl_pct is not None and pnl_pct < 0:
            severity = "warning"

        return await self.send_message(
            title=f"[매매 실행] {ticker} {action_kr}",
            message="\n".join(lines),
            severity=severity,
        )

    async def send_daily_report(self, report: dict[str, Any]) -> bool:
        """일일 리포트를 전송한다.

        Args:
            report: 일일 리포트 딕셔너리.
                keys: date, total_pnl, total_pnl_pct, trade_count,
                      positions, safety_status.

        Returns:
            발송 성공 여부.
        """
        lines = [
            f"날짜: {report.get('date', 'N/A')}",
            f"일일 수익률: {report.get('total_pnl_pct', 0.0):+.2f}%",
            f"일일 손익: ${report.get('total_pnl', 0.0):+.2f}",
            f"거래 수: {report.get('trade_count', 0)}건",
            f"활성 포지션: {report.get('positions', 0)}개",
            f"안전 상태: {report.get('safety_status', 'NORMAL')}",
        ]

        return await self.send_message(
            title="일일 트레이딩 리포트",
            message="\n".join(lines),
            severity="info",
        )

    async def send_emergency_alert(
        self,
        event_type: str,
        details: dict[str, Any],
    ) -> bool:
        """긴급 알림을 발송한다. 항상 CRITICAL 등급이다.

        Args:
            event_type: 긴급 이벤트 유형.
            details: 상세 정보 딕셔너리.

        Returns:
            발송 성공 여부.
        """
        detail_lines = [f"  {k}: {v}" for k, v in details.items()]
        message = f"이벤트: {event_type}\n" + "\n".join(detail_lines)

        return await self.send_message(
            title=f"긴급: {event_type}",
            message=message,
            severity="critical",
        )

    async def send_weekly_report(self, report: dict[str, Any]) -> bool:
        """주간 분석 리포트를 전송한다.

        Args:
            report: 주간 리포트 딕셔너리.
                keys: week_start, week_end, ai_return_pct, spy_return_pct,
                      sso_return_pct, trade_count, win_rate.

        Returns:
            발송 성공 여부.
        """
        lines = [
            f"기간: {report.get('week_start', 'N/A')} ~ {report.get('week_end', 'N/A')}",
            f"AI 수익률: {report.get('ai_return_pct', 0.0):+.2f}%",
            f"SPY 수익률: {report.get('spy_return_pct', 0.0):+.2f}%",
            f"SSO 수익률: {report.get('sso_return_pct', 0.0):+.2f}%",
            f"거래 수: {report.get('trade_count', 0)}건",
            f"승률: {report.get('win_rate', 0.0):.1f}%",
        ]

        return await self.send_message(
            title="주간 트레이딩 분석 리포트",
            message="\n".join(lines),
            severity="info",
        )

    # ------------------------------------------------------------------
    # 종합분석팀 알림
    # ------------------------------------------------------------------

    async def send_comprehensive_analysis(
        self, analysis: dict[str, Any]
    ) -> bool:
        """Pre-market 종합분석팀 분석 결과를 전송한다.

        Args:
            analysis: 종합분석팀 분석 결과 딕셔너리.
                keys: session_outlook, confidence, sector_analysis,
                      ticker_recommendations, key_risks, leader_synthesis.

        Returns:
            발송 성공 여부.
        """
        outlook = analysis.get("session_outlook", "N/A")
        confidence = analysis.get("confidence", 0.0)
        synthesis = analysis.get("leader_synthesis", "")

        # 섹터 요약
        sector_lines: list[str] = []
        for sa in analysis.get("sector_analysis", [])[:5]:
            sector = sa.get("sector", "?")
            s_outlook = sa.get("outlook", "?")
            s_conf = sa.get("confidence", 0.0)
            tickers = ", ".join(sa.get("key_tickers", [])[:3])
            emoji = (
                "\U0001f7e2" if s_outlook == "bullish"
                else "\U0001f534" if s_outlook == "bearish"
                else "\u26aa"
            )
            sector_lines.append(
                f"{emoji} {sector}: {s_outlook} ({s_conf:.0%}) [{tickers}]"
            )

        # 종목 추천 요약
        ticker_lines: list[str] = []
        for tr in analysis.get("ticker_recommendations", [])[:5]:
            ticker = tr.get("ticker", "?")
            direction = tr.get("direction", "?")
            entry = tr.get("entry_signal", "?")
            t_conf = tr.get("confidence", 0.0)
            ticker_lines.append(
                f"  {ticker}: {direction} ({entry}, {t_conf:.0%})"
            )

        # 리스크 요약
        risks = analysis.get("key_risks", [])
        risk_lines = [f"  - {r}" for r in risks[:3]]

        msg_parts: list[str] = [
            f"전망: {outlook.upper()} (확신도 {confidence:.0%})",
            "",
        ]
        if sector_lines:
            msg_parts.append("섹터 분석:")
            msg_parts.extend(sector_lines)
            msg_parts.append("")
        if ticker_lines:
            msg_parts.append("종목 추천:")
            msg_parts.extend(ticker_lines)
            msg_parts.append("")
        if risk_lines:
            msg_parts.append("핵심 리스크:")
            msg_parts.extend(risk_lines)
            msg_parts.append("")
        if synthesis:
            msg_parts.append(f"종합: {synthesis[:200]}")

        return await self.send_message(
            title="종합분석팀 Pre-Market 분석",
            message="\n".join(msg_parts),
            severity="info",
        )

    async def send_eod_analysis_report(self, report_text: str) -> bool:
        """EOD 종합분석팀 분석 보고서를 전송한다.

        Args:
            report_text: EOD 분석 보고서 텍스트 (Markdown).

        Returns:
            발송 성공 여부.
        """
        return await self.send_message(
            title="종합분석팀 EOD 분석 보고서",
            message=report_text,
            severity="info",
        )

    # ------------------------------------------------------------------
    # 봇 핸들러 통합 지원
    # ------------------------------------------------------------------

    def get_primary_bot_token(self) -> str:
        """1번 수신자(User 1)의 봇 토큰을 반환한다.

        TelegramBotHandler에서 polling용 토큰으로 사용한다.

        Returns:
            봇 토큰 문자열. 미설정 시 빈 문자열.
        """
        if self._recipients:
            return self._recipients[0].token
        return ""

    @property
    def is_enabled(self) -> bool:
        """알림 시스템 활성화 여부를 반환한다."""
        return self._enabled

    async def send_to_user(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "Markdown",
    ) -> bool:
        """특정 chat_id를 가진 사용자에게 메시지를 발송한다.

        Args:
            chat_id: 대상 텔레그램 chat ID.
            text: 발송할 메시지 본문.
            parse_mode: 메시지 파싱 모드 (기본: Markdown).

        Returns:
            발송 성공 여부.
        """
        for recipient in self._recipients:
            if recipient.chat_id == str(chat_id) and recipient.enabled:
                try:
                    bot = await self._get_bot(recipient)
                    if bot is not None:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode=parse_mode,
                        )
                        return True
                except Exception as exc:
                    logger.error(
                        "특정 사용자 Telegram 발송 실패 (chat_id=%s): %s",
                        chat_id,
                        exc,
                    )
                    return False
        logger.warning("chat_id=%s에 해당하는 수신자를 찾을 수 없음", chat_id)
        return False

    # ------------------------------------------------------------------
    # 핵심뉴스 요약 알림
    # ------------------------------------------------------------------

    async def send_key_news_alert(
        self,
        key_articles: list[dict],
        total_count: int,
        key_count: int,
        timestamp: str | None = None,
    ) -> bool:
        """핵심뉴스 요약을 텔레그램으로 전송한다.

        중요도별로 구분하여 한국어 번역 제목과 요약을 포함한
        핵심뉴스 알림 메시지를 전송한다.

        메시지 형식:
            📰 핵심뉴스 알림 (2026-02-21 18:30)
            🔴 [시장 전체] FOMC 금리 동결 결정
            연준이 금리를 5.25%로 동결했다...
            ...
            총 수집: N건 | 핵심뉴스: M건

        Args:
            key_articles: 핵심뉴스 목록.
                각 항목: {"headline", "headline_kr", "summary_ko",
                          "importance", "importance_reason"} 포함.
            total_count: 전체 수집 기사 수.
            key_count: 핵심뉴스 수.
            timestamp: 시간 문자열. None이면 현재 시간 사용.

        Returns:
            발송 성공 여부.
        """
        from datetime import datetime, timezone, timedelta

        if timestamp is None:
            # KST (UTC+9) 기준 시간
            kst = timezone(timedelta(hours=9))
            timestamp = datetime.now(tz=kst).strftime("%Y-%m-%d %H:%M")

        # 중요도별 이모지 매핑
        importance_emoji = {
            "critical": "\U0001f534",  # 빨간 원
            "high": "\U0001f7e0",      # 주황 원
            "medium": "\U0001f7e1",    # 노란 원
            "low": "\U0001f7e2",       # 초록 원
        }

        # 중요도별 카테고리 한국어
        importance_category = {
            "critical": "시장 전체",
            "high": "실적발표",
            "medium": "관련기업",
            "low": "일반",
        }

        lines: list[str] = []

        for article in key_articles:
            importance = article.get("importance", "low")
            emoji = importance_emoji.get(importance, "\U0001f7e2")
            category = importance_category.get(importance, "일반")

            # 한국어 제목 우선, 없으면 영어 원문
            title = article.get("headline_kr") or article.get("headline", "N/A")

            # 한국어 요약 (있을 경우만)
            summary = article.get("summary_ko") or ""

            lines.append(f"{emoji} [{category}] {title}")
            if summary:
                # 요약이 너무 길면 첫 2줄만
                summary_lines = [
                    ln.strip() for ln in summary.split("\n") if ln.strip()
                ]
                short_summary = " ".join(summary_lines[:2])
                if len(short_summary) > 200:
                    short_summary = short_summary[:200] + "..."
                lines.append(short_summary)
            lines.append("")  # 기사 간 빈 줄

        # 통계 요약
        lines.append(f"총 수집: {total_count}건 | 핵심뉴스: {key_count}건")

        message = "\n".join(lines).strip()

        # 빈 메시지 방어
        if not message or not key_articles:
            message = f"총 수집: {total_count}건 | 핵심뉴스 없음"

        return await self.send_message(
            title=f"핵심뉴스 알림 ({timestamp})",
            message=message,
            severity="warning",
        )

    # ------------------------------------------------------------------
    # 연결 상태 확인
    # ------------------------------------------------------------------

    async def check_connection(self) -> bool:
        """모든 수신자의 Bot 연결 상태를 확인한다.

        Returns:
            하나 이상의 Bot 연결 성공 시 True.
        """
        if not self._enabled:
            logger.info("Telegram 비활성 상태: 연결 확인 건너뜀")
            return False

        results: list[bool] = []
        for recipient in self._recipients:
            if not recipient.enabled:
                continue
            try:
                bot = await self._get_bot(recipient)
                if bot is not None:
                    me = await bot.get_me()
                    logger.info(
                        "Telegram Bot 연결 확인 (chat_id=%s): @%s",
                        recipient.chat_id,
                        me.username,
                    )
                    results.append(True)
                else:
                    results.append(False)
            except Exception as exc:
                logger.error(
                    "Telegram Bot 연결 실패 (chat_id=%s): %s",
                    recipient.chat_id,
                    exc,
                )
                results.append(False)

        return any(results)

    # ------------------------------------------------------------------
    # DB 기록
    # ------------------------------------------------------------------

    async def _log_notification(
        self,
        severity: str,
        title: str,
        message: str,
        delivered: bool,
    ) -> None:
        """알림 이력을 notification_log 테이블에 기록한다."""
        try:
            async with get_session() as session:
                log_entry = NotificationLog(
                    channel=_CHANNEL,
                    severity=severity,
                    title=title,
                    message=message,
                    sent_at=datetime.now(tz=timezone.utc),
                    delivered=delivered,
                )
                session.add(log_entry)
        except Exception as exc:
            logger.error("알림 로그 DB 기록 실패: %s", exc)
