"""
RAG document auto-generator from feedback loops.

Converts trading outcomes into persistent knowledge documents:
- Loss trades -> trade_lesson documents
- High win-rate patterns -> strategy_rule documents
- New technical patterns -> technical_pattern documents
- New ticker additions -> ticker_profile documents
- Macro regime changes -> macro_context documents
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.rag.doc_manager import RAGDocManager
from src.rag.embedder import BGEEmbedder

logger = logging.getLogger(__name__)


class RAGDocGenerator:
    """Generates RAG documents from daily/weekly feedback and market events."""

    def __init__(self, db_session: AsyncSession, embedder: BGEEmbedder) -> None:
        self.manager = RAGDocManager(db_session, embedder)

    async def generate_from_daily_feedback(
        self,
        daily_feedback: dict[str, Any],
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Generate RAG documents from a daily feedback report and trades.

        Processing rules:
        1. Loss trades (pnl_pct < -1.0%) -> trade_lesson document
        2. If daily win rate > 70% with 3+ trades -> strategy_rule document
        3. Trades with notable technical patterns -> technical_pattern document

        Args:
            daily_feedback: Daily feedback report dict with keys like
                ``date``, ``total_pnl``, ``win_rate``, ``summary``, ``lessons``.
            trades: List of trade dicts with keys like ``ticker``, ``pnl_pct``,
                ``entry_price``, ``exit_price``, ``exit_reason``, ``ai_signals``,
                ``market_regime``, ``hold_minutes``.

        Returns:
            List of created document dicts (each has ``id``, ``doc_type``, etc.).
        """
        created_docs: list[dict[str, Any]] = []
        report_date = daily_feedback.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        # 1. Loss trades -> trade_lesson
        for trade in trades:
            pnl_pct = trade.get("pnl_pct", 0.0)
            if pnl_pct is not None and pnl_pct < -1.0:
                doc = await self._create_loss_lesson(trade, report_date)
                if doc:
                    created_docs.append(doc)

        # 2. High win rate -> strategy_rule
        win_rate = daily_feedback.get("win_rate", 0.0)
        total_trades = len(trades)
        if win_rate > 70.0 and total_trades >= 3:
            doc = await self._create_win_strategy(daily_feedback, trades, report_date)
            if doc:
                created_docs.append(doc)

        # 3. Technical pattern discoveries
        for trade in trades:
            patterns = trade.get("ai_signals", [])
            if self._has_notable_pattern(patterns):
                doc = await self._create_technical_pattern(trade, patterns, report_date)
                if doc:
                    created_docs.append(doc)

        logger.info(
            "Generated %d RAG documents from daily feedback (%s, %d trades)",
            len(created_docs),
            report_date,
            total_trades,
        )
        return created_docs

    async def generate_ticker_profile(
        self,
        ticker: str,
        info: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a ticker profile document for a newly added ticker.

        Args:
            ticker: Ticker symbol (e.g., "TQQQ").
            info: Dict with keys like ``name``, ``direction``, ``leverage``,
                ``underlying``, ``expense_ratio``, ``avg_volume``,
                ``characteristics``, ``risk_factors``.

        Returns:
            Created document dict.
        """
        name = info.get("name", ticker)
        direction = info.get("direction", "unknown")
        leverage = info.get("leverage", 1.0)
        underlying = info.get("underlying", "N/A")

        content_lines = [
            f"Ticker: {ticker} ({name})",
            f"Direction: {direction}, Leverage: {leverage}x",
            f"Underlying: {underlying}",
        ]

        if expense := info.get("expense_ratio"):
            content_lines.append(f"Expense Ratio: {expense:.4f}")
        if volume := info.get("avg_volume"):
            content_lines.append(f"Avg Daily Volume: {volume:,}")
        if chars := info.get("characteristics"):
            content_lines.append(f"\nCharacteristics:\n{chars}")
        if risks := info.get("risk_factors"):
            content_lines.append(f"\nRisk Factors:\n{risks}")

        doc_id = await self.manager.create({
            "doc_type": "ticker_profile",
            "ticker": ticker,
            "title": f"{ticker} ({name}) - ETF Profile",
            "content": "\n".join(content_lines),
            "source": "system",
            "metadata": {
                "direction": direction,
                "leverage": leverage,
                "underlying": underlying,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        })

        doc = await self.manager.get(doc_id)
        logger.info("Generated ticker profile for %s: id=%s", ticker, doc_id)
        return doc

    async def update_macro_context(
        self,
        regime: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or update the macro context document (weekly).

        Args:
            regime: Current market regime (e.g., "risk_on", "risk_off",
                "neutral", "high_volatility").
            analysis: Dict with keys like ``vix_level``, ``yield_curve``,
                ``sector_rotation``, ``economic_indicators``, ``summary``.

        Returns:
            Created document dict.
        """
        summary = analysis.get("summary", "No summary provided.")
        vix = analysis.get("vix_level", "N/A")
        yield_curve = analysis.get("yield_curve", "N/A")

        content_lines = [
            f"Market Regime: {regime}",
            f"VIX Level: {vix}",
            f"Yield Curve: {yield_curve}",
        ]

        if sectors := analysis.get("sector_rotation"):
            content_lines.append(f"Sector Rotation: {sectors}")
        if indicators := analysis.get("economic_indicators"):
            content_lines.append(f"Economic Indicators: {indicators}")

        content_lines.append(f"\nSummary:\n{summary}")

        doc_id = await self.manager.create({
            "doc_type": "macro_context",
            "title": f"Macro Context - {regime} ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})",
            "content": "\n".join(content_lines),
            "source": "feedback_system",
            "metadata": {
                "regime": regime,
                "vix_level": vix,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        })

        doc = await self.manager.get(doc_id)
        logger.info("Generated macro context: regime=%s id=%s", regime, doc_id)
        return doc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_loss_lesson(
        self,
        trade: dict[str, Any],
        report_date: str,
    ) -> dict[str, Any] | None:
        """Create a trade_lesson document from a losing trade."""
        ticker = trade.get("ticker", "UNKNOWN")
        pnl_pct = trade.get("pnl_pct", 0.0)
        exit_reason = trade.get("exit_reason", "unknown")
        regime = trade.get("market_regime", "unknown")
        hold_min = trade.get("hold_minutes", 0)
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        signals = trade.get("ai_signals", [])

        content_lines = [
            f"Date: {report_date}",
            f"Ticker: {ticker}",
            f"PnL: {pnl_pct:.2f}%",
            f"Entry: {entry_price}, Exit: {exit_price}",
            f"Hold Duration: {hold_min} minutes",
            f"Exit Reason: {exit_reason}",
            f"Market Regime: {regime}",
        ]

        if signals:
            signal_strs = []
            for s in signals[:5]:  # Cap at 5 signals
                if isinstance(s, dict):
                    signal_strs.append(
                        f"  - {s.get('type', 'signal')}: {s.get('description', str(s))}"
                    )
                else:
                    signal_strs.append(f"  - {s}")
            content_lines.append("AI Signals:\n" + "\n".join(signal_strs))

        # Derive lesson
        lesson = self._derive_loss_lesson(trade)
        content_lines.append(f"\nLesson: {lesson}")

        try:
            doc_id = await self.manager.create({
                "doc_type": "trade_lesson",
                "ticker": ticker,
                "title": f"Loss Lesson: {ticker} {pnl_pct:.1f}% ({report_date})",
                "content": "\n".join(content_lines),
                "source": "daily_feedback",
                "metadata": {
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "market_regime": regime,
                    "report_date": report_date,
                },
            })
            return await self.manager.get(doc_id)
        except Exception as exc:
            logger.exception("Failed to create loss lesson for %s", ticker)
            return None

    async def _create_win_strategy(
        self,
        feedback: dict[str, Any],
        trades: list[dict[str, Any]],
        report_date: str,
    ) -> dict[str, Any] | None:
        """Create a strategy_rule document from a high-win-rate day."""
        win_rate = feedback.get("win_rate", 0.0)
        total_pnl = feedback.get("total_pnl", 0.0)
        regime = feedback.get("market_regime", "unknown")

        # Analyze winning trades for common patterns
        winning_tickers = []
        common_signals: list[str] = []
        for t in trades:
            if (t.get("pnl_pct") or 0) > 0:
                winning_tickers.append(t.get("ticker", ""))
                for s in t.get("ai_signals", []):
                    if isinstance(s, dict):
                        common_signals.append(s.get("type", str(s)))
                    else:
                        common_signals.append(str(s))

        content_lines = [
            f"Date: {report_date}",
            f"Win Rate: {win_rate:.1f}% ({len(trades)} trades)",
            f"Total PnL: {total_pnl:.2f}%",
            f"Market Regime: {regime}",
            f"Winning Tickers: {', '.join(winning_tickers)}",
        ]

        if common_signals:
            # Count signal frequency
            from collections import Counter
            signal_counts = Counter(common_signals).most_common(5)
            content_lines.append(
                "Common Signals: " + ", ".join(f"{s}({c})" for s, c in signal_counts)
            )

        summary = feedback.get("summary", "")
        if summary:
            content_lines.append(f"\nFeedback Summary:\n{summary}")

        try:
            doc_id = await self.manager.create({
                "doc_type": "strategy_rule",
                "title": f"Strategy Rule: {win_rate:.0f}% WR Day ({report_date})",
                "content": "\n".join(content_lines),
                "source": "daily_feedback",
                "metadata": {
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "trade_count": len(trades),
                    "market_regime": regime,
                    "report_date": report_date,
                },
            })
            return await self.manager.get(doc_id)
        except Exception as exc:
            logger.exception("Failed to create win strategy rule")
            return None

    async def _create_technical_pattern(
        self,
        trade: dict[str, Any],
        patterns: list[Any],
        report_date: str,
    ) -> dict[str, Any] | None:
        """Create a technical_pattern document from notable signal patterns."""
        ticker = trade.get("ticker", "UNKNOWN")
        pnl_pct = trade.get("pnl_pct", 0.0)

        pattern_lines: list[str] = []
        for p in patterns[:8]:  # Cap at 8 patterns
            if isinstance(p, dict):
                pattern_lines.append(
                    f"- {p.get('type', 'pattern')}: {p.get('description', str(p))}"
                )
            else:
                pattern_lines.append(f"- {p}")

        outcome = "PROFIT" if (pnl_pct or 0) > 0 else "LOSS"

        content_lines = [
            f"Date: {report_date}",
            f"Ticker: {ticker}",
            f"Outcome: {outcome} ({pnl_pct:.2f}%)",
            f"Patterns Detected:",
        ] + pattern_lines

        try:
            doc_id = await self.manager.create({
                "doc_type": "technical_pattern",
                "ticker": ticker,
                "title": f"Pattern: {ticker} {outcome} ({report_date})",
                "content": "\n".join(content_lines),
                "source": "daily_feedback",
                "metadata": {
                    "pnl_pct": pnl_pct,
                    "pattern_count": len(patterns),
                    "outcome": outcome,
                    "report_date": report_date,
                },
            })
            return await self.manager.get(doc_id)
        except Exception as exc:
            logger.exception("Failed to create technical pattern for %s", ticker)
            return None

    @staticmethod
    def _has_notable_pattern(patterns: list[Any]) -> bool:
        """Check if signals contain notable technical patterns worth recording."""
        if len(patterns) < 2:
            return False

        notable_keywords = {
            "divergence", "breakout", "reversal", "crossover",
            "squeeze", "exhaustion", "accumulation", "distribution",
        }
        for p in patterns:
            text = str(p).lower()
            if any(kw in text for kw in notable_keywords):
                return True
        return False

    @staticmethod
    def _derive_loss_lesson(trade: dict[str, Any]) -> str:
        """Derive a concise lesson from a losing trade based on its attributes."""
        exit_reason = (trade.get("exit_reason") or "").lower()
        pnl_pct = trade.get("pnl_pct", 0.0)
        hold_min = trade.get("hold_minutes", 0)
        regime = (trade.get("market_regime") or "").lower()

        lessons: list[str] = []

        if "stop_loss" in exit_reason:
            lessons.append("Stop loss triggered - review entry timing and position sizing")
        elif "timeout" in exit_reason or "time_limit" in exit_reason:
            lessons.append("Position timed out without reaching target - consider tighter entry criteria")
        elif "manual" in exit_reason:
            lessons.append("Manual exit - document the reasoning for future reference")

        if pnl_pct < -3.0:
            lessons.append(f"Severe loss ({pnl_pct:.1f}%) - consider reducing position size in similar setups")

        if hold_min and hold_min > 240:
            lessons.append("Long hold duration - consider shorter timeframe or momentum-based exits")

        if "high_volatility" in regime or "risk_off" in regime:
            lessons.append(f"Loss during {regime} regime - add regime filter to avoid this setup")

        if not lessons:
            lessons.append("Review entry signals and market conditions to identify what went wrong")

        return "; ".join(lessons)
