"""
텔레그램 명령 핸들러 구현.

각 슬래시 명령(/status, /positions 등)의 비즈니스 로직을 구현한다.
TradingSystem과 각종 모듈에서 데이터를 조회하여 포맷터로 전달한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.telegram import formatters
from src.telegram.permissions import Permission, check_permission
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CommandHandler:
    """텔레그램 명령을 처리하는 핸들러 클래스이다.

    TradingSystem 및 하위 모듈에 접근하여 데이터를 조회하고
    포맷터를 통해 텔레그램 메시지로 변환한다.
    """

    def __init__(self) -> None:
        self._trading_system: Any = None

    def set_trading_system(self, trading_system: Any) -> None:
        """TradingSystem 참조를 설정한다.

        Args:
            trading_system: TradingSystem 인스턴스.
        """
        self._trading_system = trading_system

    async def _translate_headlines(self, headlines: list[str]) -> dict[str, str]:
        """영어 헤드라인을 한국어로 번역한다.

        Claude Sonnet을 사용하여 영어 뉴스 헤드라인을 일괄 번역한다.
        번역 실패 시 빈 딕셔너리를 반환하여 원문을 유지한다.

        Args:
            headlines: 번역할 영어 헤드라인 문자열 리스트.

        Returns:
            {원문: 번역문} 형식의 딕셔너리. 실패 시 빈 딕셔너리.
        """
        try:
            ts = self._trading_system
            if ts is None or not hasattr(ts, "claude_client") or ts.claude_client is None:
                return {}

            if not headlines:
                return {}

            prompt = (
                "다음 영어 뉴스 헤드라인들을 한국어로 간결하게 번역해주세요.\n"
                "JSON 형식으로만 반환하세요: {\"원문\": \"번역\"}\n\n"
            )
            for h in headlines:
                prompt += f"- {h}\n"

            result = await ts.claude_client.call(
                prompt=prompt,
                task_type="telegram_chat",
            )

            json_match = re.search(
                r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", result, re.DOTALL
            )
            if json_match:
                return json.loads(json_match.group())
            return {}
        except Exception as exc:
            logger.warning("헤드라인 번역 실패: %s", exc)
            return {}

    async def handle_status(self) -> str:
        """시스템 상태를 조회하여 포맷된 메시지를 반환한다.

        Returns:
            포맷된 상태 메시지 문자열.
        """
        try:
            ts = self._trading_system
            if ts is None:
                return "\u26a0\ufe0f 시스템이 아직 초기화되지 않았습니다."

            # 포트폴리오 요약
            portfolio = {"total_value": 0.0, "cash": 0.0, "position_count": 0}
            if ts.position_monitor:
                portfolio = await ts.position_monitor.get_portfolio_summary()

            # 안전 등급
            safety_status = "NORMAL"
            if ts.safety_checker:
                status = ts.safety_checker.get_safety_status()
                safety_status = status.get("grade", "NORMAL")

            # 오늘 PnL
            today_pnl = 0.0
            today_pnl_pct = 0.0
            try:
                from sqlalchemy import and_, func, select
                from src.db.connection import get_session
                from src.db.models import Trade

                async with get_session() as session:
                    today_start = datetime.now(tz=timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    stmt = select(
                        func.coalesce(func.sum(Trade.pnl_amount), 0.0),
                    ).where(
                        and_(
                            Trade.exit_at >= today_start,
                            Trade.exit_price.isnot(None),
                        )
                    )
                    result = await session.execute(stmt)
                    today_pnl = float(result.scalar_one())

                total_value = portfolio.get("total_value", 0.0)
                if total_value > 0:
                    today_pnl_pct = round((today_pnl / total_value) * 100, 2)
            except Exception as exc:
                logger.warning("PnL 계산 실패: %s", exc)

            # 긴급 상태
            emergency_status = None
            if ts.emergency_protocol:
                try:
                    emergency_status = ts.emergency_protocol.get_status()
                except Exception as exc:
                    logger.debug("긴급 프로토콜 상태 조회 실패: %s", exc)

            return await formatters.format_status(
                portfolio=portfolio,
                safety_status=safety_status,
                today_pnl=today_pnl,
                today_pnl_pct=today_pnl_pct,
                emergency_status=emergency_status,
            )
        except Exception as exc:
            logger.error("상태 조회 실패: %s", exc)
            return f"\u274c 상태 조회 중 오류 발생: {str(exc)[:200]}"

    async def handle_positions(self) -> str:
        """보유 포지션 목록을 반환한다.

        Returns:
            포맷된 포지션 메시지 문자열.
        """
        try:
            ts = self._trading_system
            if ts is None or ts.position_monitor is None:
                return "\u26a0\ufe0f 시스템이 아직 초기화되지 않았습니다."

            portfolio = await ts.position_monitor.get_portfolio_summary()
            positions_raw = portfolio.get("positions", [])

            # dict -> list 변환 (포지션이 dict인 경우)
            if isinstance(positions_raw, dict):
                positions = list(positions_raw.values())
            else:
                positions = positions_raw

            return await formatters.format_positions(positions)
        except Exception as exc:
            logger.error("포지션 조회 실패: %s", exc)
            return f"\u274c 포지션 조회 중 오류 발생: {str(exc)[:200]}"

    async def handle_news(self, category: str | None = None) -> str:
        """최근 주요 뉴스를 반환한다.

        Args:
            category: 뉴스 카테고리 필터 (선택).

        Returns:
            포맷된 뉴스 메시지 문자열.
        """
        try:
            from sqlalchemy import select
            from src.db.connection import get_session
            from src.db.models import Article

            async with get_session() as session:
                stmt = (
                    select(Article)
                    .order_by(Article.published_at.desc())
                    .limit(30)
                )
                result = await session.execute(stmt)
                articles_orm = result.scalars().all()

            articles = []
            for a in articles_orm:
                classification = a.classification or {}
                article_data = {
                    "headline": a.headline_kr or a.headline,  # DB 번역 우선, 없으면 원문
                    "headline_original": a.headline,
                    "summary_ko": a.summary_ko,
                    "companies_impact": a.companies_impact,
                    "source": a.source,
                    "published_at": (
                        a.published_at.isoformat() if a.published_at else None
                    ),
                    "tickers": a.tickers_mentioned or [],
                    "sentiment_score": a.sentiment_score,
                    "impact": classification.get("impact", "low"),
                    "category": classification.get("category", "other"),
                    "direction": classification.get("direction", "neutral"),
                    "_has_translation": bool(a.headline_kr),
                }
                articles.append(article_data)

            # 카테고리 필터
            if category:
                articles = [
                    a for a in articles
                    if a.get("category", "").lower() == category.lower()
                ]

            # high impact 우선 정렬
            impact_order = {"high": 0, "medium": 1, "low": 2}
            articles.sort(key=lambda x: impact_order.get(x.get("impact", "low"), 2))

            # 최대 10건
            articles = articles[:10]

            # DB에 번역이 없는 기사만 온더플라이 번역 수행
            untranslated = [
                a for a in articles if not a.get("_has_translation")
            ]
            if untranslated:
                # headline_original을 번역 대상으로 사용
                headlines = [
                    a.get("headline_original", "") for a in untranslated
                    if a.get("headline_original")
                ]
                translations = await self._translate_headlines(headlines)
                for article in untranslated:
                    original = article.get("headline_original", "")
                    if original and original in translations:
                        article["headline"] = translations[original]

            return await formatters.format_news(articles)
        except Exception as exc:
            logger.error("뉴스 조회 실패: %s", exc)
            return f"\u274c 뉴스 조회 중 오류 발생: {str(exc)[:200]}"

    async def handle_analyze(self, ticker: str) -> str:
        """특정 종목을 분석한다.

        Args:
            ticker: 분석 대상 티커 (대문자).

        Returns:
            포맷된 분석 결과 메시지 문자열.
        """
        try:
            ts = self._trading_system
            if ts is None:
                return "\u26a0\ufe0f 시스템이 아직 초기화되지 않았습니다."

            ticker = ticker.upper()

            # 가격 데이터 조회
            price_data = None
            if ts.data_fetcher:
                try:
                    price_data = await ts.data_fetcher.fetch_current_price(ticker)
                except Exception as exc:
                    logger.warning("%s 가격 조회 실패: %s", ticker, exc)

            # RSI 데이터 조회
            rsi_data = None
            if ts.data_fetcher and ts.technical_calculator:
                try:
                    from src.utils.ticker_mapping import get_analysis_ticker
                    analysis_ticker = get_analysis_ticker(ticker)
                    df = await ts.data_fetcher.get_daily_prices(analysis_ticker, days=200)
                    if df is not None and not df.empty:
                        rsi_result = ts.technical_calculator.calculate_triple_rsi(df)
                        if rsi_result is not None:
                            rsi_data = {
                                "rsi_7": float(rsi_result.get("rsi_7", {}).get("rsi", 0)),
                                "rsi_14": float(rsi_result.get("rsi_14", {}).get("rsi", 0)),
                                "rsi_21": float(rsi_result.get("rsi_21", {}).get("rsi", 0)),
                                "signal_9": float(rsi_result.get("rsi_14", {}).get("signal", 0)),
                            }
                except Exception as exc:
                    logger.warning("%s RSI 계산 실패: %s", ticker, exc)

            # 현재 레짐
            regime = "unknown"
            if ts.regime_detector:
                try:
                    regime_data = await ts._get_current_regime()
                    regime = regime_data.get("regime", "unknown")
                except Exception as exc:
                    logger.debug("레짐 조회 실패: %s", exc)

            return await formatters.format_analysis(
                ticker=ticker,
                rsi_data=rsi_data,
                price_data=price_data,
                regime=regime,
            )
        except Exception as exc:
            logger.error("종목 분석 실패 (%s): %s", ticker, exc)
            return f"\u274c {ticker} 분석 중 오류 발생: {str(exc)[:200]}"

    async def handle_report(self) -> str:
        """오늘의 일일 리포트를 반환한다.

        Returns:
            포맷된 리포트 메시지 문자열.
        """
        try:
            from src.monitoring.daily_report import DailyReportGenerator

            generator = DailyReportGenerator()
            report = await generator.generate()

            return await formatters.format_report(report)
        except Exception as exc:
            logger.error("리포트 조회 실패: %s", exc)
            return f"\u274c 리포트 조회 중 오류 발생: {str(exc)[:200]}"

    async def handle_balance(self) -> str:
        """계좌 잔고 정보를 반환한다.

        Returns:
            포맷된 잔고 메시지 문자열.
        """
        try:
            ts = self._trading_system
            if ts is None or ts.position_monitor is None:
                return "\u26a0\ufe0f 시스템이 아직 초기화되지 않았습니다."

            portfolio = await ts.position_monitor.get_portfolio_summary()
            total_value = portfolio.get("total_value", 0.0)
            cash = portfolio.get("cash", 0.0)

            balance = {
                "total_value": total_value,
                "cash": cash,
                "invested": total_value - cash,
            }

            return await formatters.format_balance(balance)
        except Exception as exc:
            logger.error("잔고 조회 실패: %s", exc)
            return f"\u274c 잔고 조회 중 오류 발생: {str(exc)[:200]}"

    async def handle_help(self, is_admin: bool) -> str:
        """도움말 메시지를 반환한다.

        Args:
            is_admin: 관리자(User 1) 여부.

        Returns:
            포맷된 도움말 메시지 문자열.
        """
        return await formatters.format_help(is_admin)

    async def handle_stop(self) -> str:
        """매매를 긴급 중단한다.

        Returns:
            결과 메시지 문자열.
        """
        try:
            ts = self._trading_system
            if ts is None or ts.emergency_protocol is None:
                return "\u26a0\ufe0f 시스템이 아직 초기화되지 않았습니다."

            positions = []
            if ts.position_monitor:
                portfolio = await ts.position_monitor.get_portfolio_summary()
                positions_raw = portfolio.get("positions", [])
                # dict -> list 변환 (포지션이 dict인 경우)
                if isinstance(positions_raw, dict):
                    positions = list(positions_raw.values())
                else:
                    positions = positions_raw

            result = await ts.emergency_protocol.handle_runaway_loss(positions)

            return (
                "\U0001f6d1 *매매 긴급 중단*\n\n"
                "모든 매매가 중단되었습니다.\n"
                "재개하려면 /resume 명령을 사용하세요."
            )
        except Exception as exc:
            logger.error("긴급 중단 실패: %s", exc)
            return f"\u274c 긴급 중단 실패: {str(exc)[:200]}"

    async def handle_resume(self) -> str:
        """매매를 재개한다.

        Returns:
            결과 메시지 문자열.
        """
        try:
            ts = self._trading_system
            if ts is None or ts.emergency_protocol is None:
                return "\u26a0\ufe0f 시스템이 아직 초기화되지 않았습니다."

            ts.emergency_protocol.is_runaway_loss_shutdown = False
            ts.emergency_protocol.is_circuit_breaker_active = False
            ts.emergency_protocol.reset_daily()

            return (
                "\u2705 *매매 재개*\n\n"
                "긴급 중단이 해제되었습니다.\n"
                "정상적인 매매 루프가 재개됩니다."
            )
        except Exception as exc:
            logger.error("매매 재개 실패: %s", exc)
            return f"\u274c 매매 재개 실패: {str(exc)[:200]}"
