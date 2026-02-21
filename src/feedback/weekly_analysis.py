"""
주간 심층 분석 모듈.

Claude Opus 심층 분석 + 파라미터 조정 제안을 생성한다.
- 해당 주 전체 매매 기록 로드 (월~금)
- 주간 통계 계산 (일별 분해 포함)
- Claude Opus 심층 분석
- 파라미터 조정 제안 생성 (pending_adjustments 테이블)

Thinking.md Part 4.3 기반.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import build_weekly_analysis_prompt, get_system_prompt
from src.db.connection import get_session
from src.db.models import FeedbackReport, Trade
from src.feedback.param_adjuster import ParamAdjuster
from src.strategy.params import StrategyParams
from src.utils.logger import get_logger

logger = get_logger(__name__)


class WeeklyAnalysis:
    """주간 심층 분석 생성기.

    매주 일요일에 자동 실행되어 한 주간의 매매 결과를 종합 분석하고,
    시스템 파라미터 조정을 제안한다.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        param_adjuster: ParamAdjuster,
    ) -> None:
        """WeeklyAnalysis 초기화.

        Args:
            claude_client: Claude API 클라이언트 (Opus 모델 사용).
            param_adjuster: 파라미터 자동 조정 모듈.
        """
        self.client = claude_client
        self.adjuster = param_adjuster

    async def generate(self, week_start: str | None = None) -> dict[str, Any]:
        """주간 심층 분석을 생성한다.

        1. 해당 주 전체 매매 기록 로드 (월~금)
        2. 주간 통계 계산
        3. Claude Opus 심층 분석
        4. 파라미터 조정 제안 생성 (pending_adjustments 테이블)

        Args:
            week_start: 주 시작일 (월요일, YYYY-MM-DD). None이면 직전 월요일.

        Returns:
            주간 분석 결과 딕셔너리::

                {
                    "week": str,
                    "summary": {...},
                    "analysis": {...},
                    "param_adjustments": [...],
                    "recommendations": [...],
                }
        """
        if week_start is None:
            today = datetime.now(timezone.utc).date()
            # 직전 월요일 계산 (오늘이 월요일이면 지난주 월요일)
            days_since_monday = today.weekday()
            if days_since_monday == 0:
                days_since_monday = 7
            monday = today - timedelta(days=days_since_monday)
            week_start = monday.isoformat()

        logger.info("주간 심층 분석 시작 | week_start=%s", week_start)

        # 1. 주간 매매 기록 로드
        trades = await self._load_weekly_trades(week_start)
        if not trades:
            logger.info("주간 매매 기록 없음 | week_start=%s", week_start)
            return {
                "week": week_start,
                "summary": {},
                "analysis": {},
                "param_adjustments": [],
                "recommendations": [],
            }

        # 2. 주간 통계 계산
        summary = self._calculate_weekly_summary(trades, week_start)
        logger.info(
            "주간 통계 계산 완료 | week=%s | trades=%d | win_rate=%.1f%% | pnl=%.2f%%",
            week_start,
            summary["total_trades"],
            summary["win_rate"],
            summary["total_pnl_pct"],
        )

        # 3. 현재 파라미터 가져오기
        current_params = self.adjuster.params.to_dict()

        # 4. Claude Opus 심층 분석
        prompt = build_weekly_analysis_prompt(
            weekly_trades=trades,
            weekly_summary=summary,
            current_params=current_params,
        )
        analysis = await self.client.call_json(
            prompt=prompt,
            task_type="weekly_analysis",
            system_prompt=get_system_prompt("weekly_analysis"),
            max_tokens=8192,
            use_cache=False,
        )
        logger.info("Claude 주간 심층 분석 완료 | week=%s", week_start)

        # 5. 파라미터 조정 제안 생성
        param_adjustments: list[dict[str, Any]] = []
        if isinstance(analysis, dict):
            raw_adjustments = analysis.get("param_adjustments", [])
            for adj in raw_adjustments:
                if not isinstance(adj, dict):
                    continue
                param_name = adj.get("param", "")
                suggested = adj.get("suggested_value")
                reason = adj.get("reason", "")

                if not param_name or suggested is None:
                    continue

                try:
                    suggested_float = float(suggested)
                except (ValueError, TypeError):
                    logger.warning(
                        "파라미터 조정값 변환 실패 | param=%s | value=%s",
                        param_name,
                        suggested,
                    )
                    continue

                proposal = await self.adjuster.propose_adjustment(
                    param_name=param_name,
                    new_value=suggested_float,
                    reason=reason,
                )
                param_adjustments.append(proposal)

        # 6. 추천사항 추출
        recommendations: list[str] = []
        if isinstance(analysis, dict):
            if next_week := analysis.get("next_week_strategy"):
                recommendations.append(next_week)
            if profit_patterns := analysis.get("profit_patterns"):
                recommendations.extend(profit_patterns)

        # 7. 결과 조합 및 DB 저장
        report = {
            "week": week_start,
            "summary": summary,
            "analysis": analysis,
            "param_adjustments": param_adjustments,
            "recommendations": recommendations,
        }

        await self._save_report(week_start, report)

        logger.info(
            "주간 심층 분석 완료 | week=%s | adjustments=%d",
            week_start,
            len(param_adjustments),
        )
        return report

    async def _load_weekly_trades(self, week_start: str) -> list[dict[str, Any]]:
        """해당 주 매매 기록을 로드한다 (월~금).

        Args:
            week_start: 주 시작일 (월요일, YYYY-MM-DD).

        Returns:
            매매 기록 딕셔너리 목록.
        """
        start_date = date.fromisoformat(week_start)
        end_date = start_date + timedelta(days=5)  # 월~금

        start_dt = datetime(
            start_date.year, start_date.month, start_date.day,
            tzinfo=timezone.utc,
        )
        end_dt = datetime(
            end_date.year, end_date.month, end_date.day,
            23, 59, 59, tzinfo=timezone.utc,
        )

        async with get_session() as session:
            stmt = (
                select(Trade)
                .where(
                    Trade.exit_at >= start_dt,
                    Trade.exit_at <= end_dt,
                    Trade.exit_price.is_not(None),
                )
                .order_by(Trade.entry_at)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        trades: list[dict[str, Any]] = []
        for row in rows:
            trades.append({
                "id": str(row.id),
                "ticker": row.ticker,
                "direction": row.direction,
                "entry_price": row.entry_price,
                "exit_price": row.exit_price,
                "entry_at": row.entry_at.isoformat() if row.entry_at else None,
                "exit_at": row.exit_at.isoformat() if row.exit_at else None,
                "pnl_pct": row.pnl_pct,
                "pnl_amount": row.pnl_amount,
                "hold_minutes": row.hold_minutes,
                "exit_reason": row.exit_reason,
                "ai_confidence": row.ai_confidence,
                "ai_signals": row.ai_signals or [],
                "market_regime": row.market_regime,
            })

        logger.info(
            "주간 매매 기록 로드 완료 | week=%s | count=%d",
            week_start,
            len(trades),
        )
        return trades

    def _calculate_weekly_summary(
        self, trades: list[dict[str, Any]], week_start: str
    ) -> dict[str, Any]:
        """주간 통계를 계산한다 (일별 분해 포함).

        Args:
            trades: 주간 매매 기록 목록.
            week_start: 주 시작일 (YYYY-MM-DD).

        Returns:
            주간 통계 딕셔너리::

                {
                    "total_trades", "win_count", "loss_count", "win_rate",
                    "total_pnl_pct", "total_pnl_amount", "avg_hold_minutes",
                    "max_drawdown_pct", "consecutive_losses", "daily_breakdown",
                    "ticker_breakdown", "regime_breakdown",
                }
        """
        total_trades = len(trades)
        win_count = 0
        loss_count = 0
        total_pnl_pct = 0.0
        total_pnl_amount = 0.0
        total_hold_minutes = 0
        hold_count = 0

        # 일별 분해
        daily_stats: dict[str, dict[str, Any]] = {}
        # 종목별 분해
        ticker_stats: dict[str, dict[str, Any]] = {}
        # 레짐별 분해
        regime_stats: dict[str, dict[str, Any]] = {}

        # 연속 손실 추적
        max_consecutive_losses = 0
        current_consecutive_losses = 0

        # 최대 낙폭 추적
        cumulative_pnl = 0.0
        peak_pnl = 0.0
        max_drawdown = 0.0

        for trade in trades:
            pnl_pct = trade.get("pnl_pct") or 0.0
            pnl_amount = trade.get("pnl_amount") or 0.0

            if pnl_pct > 0:
                win_count += 1
                current_consecutive_losses = 0
            elif pnl_pct < 0:
                loss_count += 1
                current_consecutive_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)

            total_pnl_pct += pnl_pct
            total_pnl_amount += pnl_amount

            # 최대 낙폭 계산
            cumulative_pnl += pnl_pct
            peak_pnl = max(peak_pnl, cumulative_pnl)
            drawdown = peak_pnl - cumulative_pnl
            max_drawdown = max(max_drawdown, drawdown)

            hold_min = trade.get("hold_minutes")
            if hold_min is not None:
                total_hold_minutes += hold_min
                hold_count += 1

            # 일별 분해
            exit_at = trade.get("exit_at", "")
            trade_date = exit_at[:10] if exit_at else "unknown"
            if trade_date not in daily_stats:
                daily_stats[trade_date] = {
                    "trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0.0,
                }
            day = daily_stats[trade_date]
            day["trades"] += 1
            day["pnl_pct"] += pnl_pct
            if pnl_pct > 0:
                day["wins"] += 1
            elif pnl_pct < 0:
                day["losses"] += 1

            # 종목별 분해
            ticker = trade.get("ticker", "UNKNOWN")
            if ticker not in ticker_stats:
                ticker_stats[ticker] = {
                    "trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0.0,
                }
            ts = ticker_stats[ticker]
            ts["trades"] += 1
            ts["pnl_pct"] += pnl_pct
            if pnl_pct > 0:
                ts["wins"] += 1
            elif pnl_pct < 0:
                ts["losses"] += 1

            # 레짐별 분해
            regime = trade.get("market_regime") or "unknown"
            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0.0,
                }
            rs = regime_stats[regime]
            rs["trades"] += 1
            rs["pnl_pct"] += pnl_pct
            if pnl_pct > 0:
                rs["wins"] += 1
            elif pnl_pct < 0:
                rs["losses"] += 1

        # 일별 통계에 승률 추가
        for day_data in daily_stats.values():
            t = day_data["trades"]
            day_data["win_rate"] = round(day_data["wins"] / t * 100, 2) if t > 0 else 0.0
            day_data["pnl_pct"] = round(day_data["pnl_pct"], 4)

        # 종목별 통계에 승률 추가
        for ts_data in ticker_stats.values():
            t = ts_data["trades"]
            ts_data["win_rate"] = round(ts_data["wins"] / t * 100, 2) if t > 0 else 0.0
            ts_data["pnl_pct"] = round(ts_data["pnl_pct"], 4)

        # 레짐별 통계에 승률 추가
        for rs_data in regime_stats.values():
            t = rs_data["trades"]
            rs_data["win_rate"] = round(rs_data["wins"] / t * 100, 2) if t > 0 else 0.0
            rs_data["pnl_pct"] = round(rs_data["pnl_pct"], 4)

        win_rate = (win_count / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_hold = (total_hold_minutes / hold_count) if hold_count > 0 else 0.0

        return {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "total_pnl_amount": round(total_pnl_amount, 2),
            "avg_hold_minutes": round(avg_hold, 1),
            "max_drawdown_pct": round(max_drawdown, 4),
            "consecutive_losses": max_consecutive_losses,
            "daily_breakdown": daily_stats,
            "ticker_breakdown": ticker_stats,
            "regime_breakdown": regime_stats,
        }

    async def _save_report(self, week_start: str, report: dict[str, Any]) -> None:
        """feedback_reports 테이블에 주간 분석 보고서를 저장한다.

        Args:
            week_start: 주 시작일 (YYYY-MM-DD).
            report: 저장할 주간 분석 보고서.
        """
        from uuid import uuid4

        parsed_date = date.fromisoformat(week_start)

        async with get_session() as session:
            record = FeedbackReport(
                id=str(uuid4()),
                report_type="weekly",
                report_date=parsed_date,
                content=report,
            )
            session.add(record)

        logger.info("주간 분석 보고서 저장 완료 | week=%s", week_start)
