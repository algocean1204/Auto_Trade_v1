"""
Daily report generator for the AI Trading System V2.

Aggregates trade data, performance metrics, and system statistics
into a structured report for the dashboard. Stores reports in the
feedback_reports table for historical access.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, and_, cast, Date

from src.db.connection import get_session
from src.db.models import Trade, FeedbackReport, PendingAdjustment
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 지표 피드백 분석 대상 지표 목록
_INDICATOR_FEEDBACK_TARGETS = [
    "rsi_7", "rsi_14", "rsi_21", "macd", "stochastic", "ma_cross",
]


class DailyReportGenerator:
    """Generate daily performance reports by aggregating trade data.

    Reports include:
        - Trade summary (count, win/loss, total PnL)
        - Per-ticker breakdown
        - Hourly distribution
        - Risk metrics (max drawdown, avg holding time)
        - System health summary
        - Indicator feedback (지표별 진입 성과 분석)
    """

    async def generate(self, target_date: str | None = None) -> dict[str, Any]:
        """Generate a daily report for the given date.

        If the report already exists in the database it is returned directly.
        Otherwise a fresh one is computed from the trades table.

        Args:
            target_date: Date string in YYYY-MM-DD format. Defaults to today (UTC).

        Returns:
            Report dictionary with aggregated metrics.
        """
        if target_date is None:
            report_date = date.today()
        else:
            report_date = date.fromisoformat(target_date)

        logger.info("Generating daily report for %s", report_date.isoformat())

        # Check for existing report
        existing = await self._load_existing(report_date)
        if existing is not None:
            logger.info("Returning cached daily report for %s", report_date.isoformat())
            return existing

        # Generate new report
        trades = await self._fetch_trades(report_date)
        report = self._aggregate(trades, report_date)

        # Persist
        await self._save_report(report_date, report)

        logger.info(
            "Daily report generated | date=%s | trades=%d | pnl=%.2f",
            report_date.isoformat(),
            report["summary"]["total_trades"],
            report["summary"]["total_pnl"],
        )
        return report

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def _fetch_trades(self, report_date: date) -> list[dict[str, Any]]:
        """Fetch all closed trades for the given date.

        Trades are matched by exit_at date.

        Args:
            report_date: Target date.

        Returns:
            List of trade dictionaries.
        """
        try:
            async with get_session() as session:
                day_start = datetime.combine(
                    report_date, datetime.min.time(), tzinfo=timezone.utc
                )
                day_end = day_start + timedelta(days=1)

                stmt = (
                    select(Trade)
                    .where(
                        and_(
                            Trade.exit_at >= day_start,
                            Trade.exit_at < day_end,
                            Trade.exit_price.isnot(None),
                        )
                    )
                    .order_by(Trade.exit_at)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                trades: list[dict[str, Any]] = []
                for row in rows:
                    trades.append({
                        "id": row.id,
                        "ticker": row.ticker,
                        "direction": row.direction,
                        "entry_price": row.entry_price,
                        "exit_price": row.exit_price,
                        "entry_at": row.entry_at.isoformat() if row.entry_at else None,
                        "exit_at": row.exit_at.isoformat() if row.exit_at else None,
                        "pnl_pct": row.pnl_pct or 0.0,
                        "pnl_amount": row.pnl_amount or 0.0,
                        "hold_minutes": row.hold_minutes or 0,
                        "exit_reason": row.exit_reason or "",
                        "ai_confidence": row.ai_confidence or 0.0,
                        "market_regime": row.market_regime or "",
                        "ai_signals": row.ai_signals or [],
                    })

                return trades
        except Exception as exc:
            logger.error("Failed to fetch trades for %s: %s", report_date, exc)
            return []

    async def _load_existing(self, report_date: date) -> dict[str, Any] | None:
        """Load an existing report from the database.

        Args:
            report_date: Target date.

        Returns:
            Report content or None if not found.
        """
        try:
            async with get_session() as session:
                stmt = select(FeedbackReport).where(
                    and_(
                        FeedbackReport.report_type == "daily_performance",
                        FeedbackReport.report_date == report_date,
                    )
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row is not None:
                    return row.content
        except Exception as exc:
            logger.error("Failed to load existing report: %s", exc)
        return None

    async def _save_report(
        self, report_date: date, content: dict[str, Any]
    ) -> None:
        """Persist the report to the feedback_reports table.

        Args:
            report_date: Target date.
            content: Report content dictionary.
        """
        try:
            async with get_session() as session:
                report = FeedbackReport(
                    report_type="daily_performance",
                    report_date=report_date,
                    content=content,
                )
                session.add(report)
        except Exception as exc:
            logger.error("Failed to save daily report: %s", exc)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(
        self, trades: list[dict[str, Any]], report_date: date
    ) -> dict[str, Any]:
        """Aggregate trade data into the report structure.

        Args:
            trades: List of trade dictionaries.
            report_date: Target date.

        Returns:
            Structured report dictionary.
        """
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "date": report_date.isoformat(),
                "summary": {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_pnl_pct": 0.0,
                    "max_win_pct": 0.0,
                    "max_loss_pct": 0.0,
                    "avg_hold_minutes": 0,
                },
                "by_ticker": {},
                "by_hour": {},
                "by_exit_reason": {},
                "risk_metrics": {
                    "max_drawdown_pct": 0.0,
                    "sharpe_estimate": 0.0,
                    "avg_confidence": 0.0,
                },
                "indicator_feedback": self._build_empty_indicator_feedback(),
            }

        pnl_values = [t["pnl_pct"] for t in trades]
        pnl_amounts = [t["pnl_amount"] for t in trades]
        winning = [t for t in trades if t["pnl_pct"] > 0]
        losing = [t for t in trades if t["pnl_pct"] <= 0]

        # Per-ticker breakdown
        by_ticker: dict[str, dict[str, Any]] = {}
        for t in trades:
            ticker = t["ticker"]
            if ticker not in by_ticker:
                by_ticker[ticker] = {
                    "trades": 0,
                    "total_pnl": 0.0,
                    "avg_pnl_pct": 0.0,
                    "pnl_values": [],
                }
            by_ticker[ticker]["trades"] += 1
            by_ticker[ticker]["total_pnl"] += t["pnl_amount"]
            by_ticker[ticker]["pnl_values"].append(t["pnl_pct"])

        for ticker, info in by_ticker.items():
            vals = info.pop("pnl_values")
            info["avg_pnl_pct"] = round(sum(vals) / len(vals), 4) if vals else 0.0

        # Hourly distribution
        by_hour: dict[str, int] = {}
        for t in trades:
            if t["exit_at"]:
                hour = t["exit_at"][:13]  # "YYYY-MM-DDTHH"
                by_hour[hour] = by_hour.get(hour, 0) + 1

        # By exit reason
        by_exit_reason: dict[str, int] = {}
        for t in trades:
            reason = t["exit_reason"] or "unknown"
            by_exit_reason[reason] = by_exit_reason.get(reason, 0) + 1

        # Risk metrics
        confidences = [t["ai_confidence"] for t in trades if t["ai_confidence"] > 0]
        hold_minutes = [t["hold_minutes"] for t in trades if t["hold_minutes"] > 0]

        # Running max drawdown
        max_dd = 0.0
        running_sum = 0.0
        peak = 0.0
        for pnl in pnl_amounts:
            running_sum += pnl
            if running_sum > peak:
                peak = running_sum
            dd = peak - running_sum
            if dd > max_dd:
                max_dd = dd

        max_dd_pct = 0.0
        if peak > 0:
            max_dd_pct = round((max_dd / peak) * 100, 2)

        avg_pnl = sum(pnl_values) / total_trades if total_trades > 0 else 0.0
        std_pnl = (
            (sum((p - avg_pnl) ** 2 for p in pnl_values) / total_trades) ** 0.5
            if total_trades > 1
            else 0.0
        )
        sharpe_estimate = round(avg_pnl / std_pnl, 4) if std_pnl > 0 else 0.0

        # Indicator feedback 분석
        indicator_feedback = self._build_indicator_feedback(trades)

        return {
            "date": report_date.isoformat(),
            "summary": {
                "total_trades": total_trades,
                "winning_trades": len(winning),
                "losing_trades": len(losing),
                "win_rate": round(len(winning) / total_trades * 100, 2),
                "total_pnl": round(sum(pnl_amounts), 2),
                "avg_pnl_pct": round(avg_pnl, 4),
                "max_win_pct": round(max(pnl_values), 4) if pnl_values else 0.0,
                "max_loss_pct": round(min(pnl_values), 4) if pnl_values else 0.0,
                "avg_hold_minutes": (
                    round(sum(hold_minutes) / len(hold_minutes))
                    if hold_minutes
                    else 0
                ),
            },
            "by_ticker": by_ticker,
            "by_hour": by_hour,
            "by_exit_reason": by_exit_reason,
            "risk_metrics": {
                "max_drawdown_pct": max_dd_pct,
                "sharpe_estimate": sharpe_estimate,
                "avg_confidence": (
                    round(sum(confidences) / len(confidences), 4)
                    if confidences
                    else 0.0
                ),
            },
            "indicator_feedback": indicator_feedback,
        }

    # ------------------------------------------------------------------
    # Indicator Feedback
    # ------------------------------------------------------------------

    def _build_empty_indicator_feedback(self) -> dict[str, Any]:
        """거래 없을 때 빈 지표 피드백 구조를 반환한다."""
        feedback: dict[str, Any] = {}
        for indicator in _INDICATOR_FEEDBACK_TARGETS:
            feedback[indicator] = {
                "avg_entry_value": 0.0,
                "profitable_entries": 0,
                "total_entries": 0,
                "avg_pnl_when_bullish": 0.0,
            }
        feedback["recommendation"] = "거래 데이터가 없어 지표 피드백을 생성할 수 없습니다."
        return feedback

    def _build_indicator_feedback(
        self, trades: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """ai_signals JSONB를 분석하여 지표별 진입 성과를 집계한다.

        Trade.ai_signals에 저장된 진입 시점 지표 신호를 활용하여
        각 지표의 방향 신호와 이후 손익 간 상관관계를 분석한다.

        Args:
            trades: 거래 목록. 각 항목에 ai_signals 필드 포함.

        Returns:
            지표별 피드백 딕셔너리와 종합 권고사항.
        """
        # 지표별 집계 버킷 초기화
        buckets: dict[str, dict[str, Any]] = {
            name: {
                "entry_values": [],       # 진입 시점 RSI / histogram 등 스칼라 값
                "pnl_when_bullish": [],   # bullish 신호로 진입한 거래의 pnl_pct
                "pnl_when_bearish": [],   # bearish 신호로 진입한 거래의 pnl_pct
                "total": 0,
                "profitable": 0,
            }
            for name in _INDICATOR_FEEDBACK_TARGETS
        }

        for trade in trades:
            pnl = trade.get("pnl_pct", 0.0)
            ai_signals = trade.get("ai_signals") or []

            if not isinstance(ai_signals, list):
                continue

            for signal_item in ai_signals:
                if not isinstance(signal_item, dict):
                    continue

                indicator_name = signal_item.get("indicator")
                if indicator_name not in buckets:
                    continue

                bucket = buckets[indicator_name]
                bucket["total"] += 1
                if pnl > 0:
                    bucket["profitable"] += 1

                # 스칼라 값 추출 (RSI 계열은 rsi 필드 우선)
                raw_val = signal_item.get("raw_value")
                if isinstance(raw_val, dict):
                    scalar = float(raw_val.get("rsi", raw_val.get("histogram", 0.0)))
                elif isinstance(raw_val, (int, float)):
                    scalar = float(raw_val)
                else:
                    scalar = 0.0
                bucket["entry_values"].append(scalar)

                # 신호 방향별 pnl 분류
                ctx = signal_item.get("contextual_signal") or {}
                direction = ctx.get("direction", "neutral")
                if direction in ("bullish", "bullish_despite_overbought"):
                    bucket["pnl_when_bullish"].append(pnl)
                elif direction in ("bearish", "bearish_despite_oversold"):
                    bucket["pnl_when_bearish"].append(pnl)

        # 집계 결과 정리
        feedback: dict[str, Any] = {}
        problem_indicators: list[str] = []

        for name, bucket in buckets.items():
            total = bucket["total"]
            profitable = bucket["profitable"]
            entry_values = bucket["entry_values"]
            bullish_pnls = bucket["pnl_when_bullish"]

            avg_entry = round(sum(entry_values) / len(entry_values), 2) if entry_values else 0.0
            avg_pnl_bullish = (
                round(sum(bullish_pnls) / len(bullish_pnls), 4) if bullish_pnls else 0.0
            )

            feedback[name] = {
                "avg_entry_value": avg_entry,
                "profitable_entries": profitable,
                "total_entries": total,
                "avg_pnl_when_bullish": avg_pnl_bullish,
            }

            # 과매수 구간(RSI >= 70) 진입 후 승률이 낮은지 검사
            if total > 0 and (profitable / total) < 0.4:
                problem_indicators.append(name)

        # 권고사항 생성
        feedback["recommendation"] = self._generate_recommendation(
            feedback, problem_indicators
        )

        return feedback

    @staticmethod
    def _generate_recommendation(
        feedback: dict[str, Any], problem_indicators: list[str]
    ) -> str:
        """지표 피드백 기반 권고사항을 생성한다.

        Args:
            feedback: 지표별 피드백 딕셔너리.
            problem_indicators: 성과가 낮은 지표 목록.

        Returns:
            권고사항 문자열.
        """
        if not problem_indicators:
            return "전체 지표의 승률이 양호합니다. 현재 설정을 유지하세요."

        parts: list[str] = []
        for name in problem_indicators:
            info = feedback.get(name, {})
            total = info.get("total_entries", 0)
            profitable = info.get("profitable_entries", 0)
            win_rate = round(profitable / total * 100, 1) if total > 0 else 0.0
            avg_entry = info.get("avg_entry_value", 0.0)

            if "rsi" in name:
                if avg_entry >= 70:
                    parts.append(
                        f"{name.upper()}가 {avg_entry:.1f} 과매수 구간 진입 승률 "
                        f"{win_rate}%. 과매수 기준 강화(70→75) 권장."
                    )
                elif avg_entry <= 30:
                    parts.append(
                        f"{name.upper()}가 {avg_entry:.1f} 과매도 구간 진입 승률 "
                        f"{win_rate}%. 반등 확인 후 진입 권장."
                    )
                else:
                    parts.append(
                        f"{name.upper()} 진입 승률 {win_rate}%. 신호 신뢰도 검토 권장."
                    )
            else:
                parts.append(
                    f"{name.upper()} 진입 승률 {win_rate}% (진입 {total}건). "
                    f"가중치 조정 검토 권장."
                )

        return " | ".join(parts)
