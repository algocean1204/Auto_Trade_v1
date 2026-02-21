"""
일일 피드백 모듈.

매매 종료 후 Claude Opus가 자동 분석하여 일일 피드백을 생성한다.
- 해당일 trades 테이블에서 매매 기록 로드
- 기본 통계 계산 (총손익, 승률, 평균보유시간 등)
- Claude Opus에 일일 피드백 프롬프트 전송
- 결과를 feedback_reports 테이블에 저장
- RAG 문서 자동 생성 (손실 교훈, 수익 패턴)

Thinking.md Part 4.2 기반.
"""

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import build_daily_feedback_prompt, get_system_prompt
from src.db.connection import get_session
from src.db.models import FeedbackReport, Trade
from src.feedback.rag_doc_updater import RAGDocUpdater
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DailyFeedback:
    """일일 피드백 생성기.

    장 마감 후 당일 매매 기록을 분석하여 Claude Opus 기반 피드백을 생성한다.
    생성된 피드백은 DB에 저장되고, RAG 문서로 자동 변환된다.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        rag_doc_updater: RAGDocUpdater,
    ) -> None:
        """DailyFeedback 초기화.

        Args:
            claude_client: Claude API 클라이언트 (Opus 모델 사용).
            rag_doc_updater: RAG 문서 자동 생성 연동 모듈.
        """
        self.client = claude_client
        self.rag_updater = rag_doc_updater

    async def generate(self, target_date: str | None = None) -> dict[str, Any]:
        """일일 피드백을 생성한다.

        1. 해당일 trades 테이블에서 매매 기록 로드
        2. 기본 통계 계산 (총손익, 승률, 평균보유시간 등)
        3. Claude Opus에 일일 피드백 프롬프트 전송
        4. 결과를 feedback_reports 테이블에 저장
        5. RAG 문서 자동 생성 (손실 교훈, 수익 패턴)

        Args:
            target_date: 분석 대상 날짜 (YYYY-MM-DD). None이면 오늘.

        Returns:
            피드백 결과 딕셔너리::

                {
                    "date": str,
                    "summary": {...},
                    "analysis": {...},
                    "improvements": [...],
                    "rag_docs_created": int,
                }
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        elif isinstance(target_date, date) and not isinstance(target_date, datetime):
            target_date = target_date.isoformat()

        logger.info("일일 피드백 생성 시작 | date=%s", target_date)

        # 1. 매매 기록 로드
        trades = await self._load_trades(target_date)
        if not trades:
            logger.info("매매 기록 없음 | date=%s", target_date)
            return {
                "date": target_date,
                "summary": {},
                "analysis": {},
                "improvements": [],
                "rag_docs_created": 0,
            }

        # 2. 기본 통계 계산
        summary = self._calculate_summary(trades)
        logger.info(
            "일일 통계 계산 완료 | date=%s | trades=%d | win_rate=%.1f%% | pnl=%.2f%%",
            target_date,
            summary["total_trades"],
            summary["win_rate"],
            summary["total_pnl_pct"],
        )

        # 3. Claude Opus 분석
        prompt = build_daily_feedback_prompt(trades=trades, summary=summary)
        analysis = await self.client.call_json(
            prompt=prompt,
            task_type="daily_feedback",
            system_prompt=get_system_prompt("daily_feedback"),
            max_tokens=4096,
            use_cache=False,
        )
        logger.info("Claude 일일 피드백 분석 완료 | date=%s", target_date)

        # 4. 개선사항 추출
        improvements = []
        if isinstance(analysis, dict):
            improvements = analysis.get("improvements", [])

        # 5. 결과 조합
        report = {
            "date": target_date,
            "summary": summary,
            "analysis": analysis,
            "improvements": improvements,
        }

        # 6. DB 저장
        await self._save_report(target_date, report)

        # 7. RAG 문서 생성
        rag_count = await self._generate_rag_docs(report, trades)
        report["rag_docs_created"] = rag_count

        logger.info(
            "일일 피드백 생성 완료 | date=%s | rag_docs=%d",
            target_date,
            rag_count,
        )
        return report

    async def _load_trades(self, target_date: str) -> list[dict[str, Any]]:
        """DB에서 해당일 매매 기록을 로드한다.

        exit_at 기준으로 해당 날짜의 완료된 거래만 조회한다.

        Args:
            target_date: YYYY-MM-DD 형식 날짜 문자열.

        Returns:
            매매 기록 딕셔너리 목록.
        """
        parsed_date = target_date if isinstance(target_date, date) else date.fromisoformat(target_date)
        start_dt = datetime(
            parsed_date.year, parsed_date.month, parsed_date.day,
            tzinfo=timezone.utc,
        )
        end_dt = datetime(
            parsed_date.year, parsed_date.month, parsed_date.day,
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

        logger.info("매매 기록 로드 완료 | date=%s | count=%d", target_date, len(trades))
        return trades

    def _calculate_summary(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """기본 통계를 계산한다.

        Args:
            trades: 매매 기록 딕셔너리 목록.

        Returns:
            통계 딕셔너리::

                {
                    "total_trades", "win_count", "loss_count", "win_rate",
                    "total_pnl_pct", "total_pnl_amount", "avg_hold_minutes",
                    "best_trade", "worst_trade", "avg_confidence",
                }
        """
        total_trades = len(trades)
        win_count = 0
        loss_count = 0
        total_pnl_pct = 0.0
        total_pnl_amount = 0.0
        total_hold_minutes = 0
        hold_count = 0
        total_confidence = 0.0
        confidence_count = 0

        best_trade: dict[str, Any] | None = None
        worst_trade: dict[str, Any] | None = None
        best_pnl = float("-inf")
        worst_pnl = float("inf")

        for trade in trades:
            pnl_pct = trade.get("pnl_pct") or 0.0
            pnl_amount = trade.get("pnl_amount") or 0.0

            if pnl_pct > 0:
                win_count += 1
            elif pnl_pct < 0:
                loss_count += 1

            total_pnl_pct += pnl_pct
            total_pnl_amount += pnl_amount

            hold_min = trade.get("hold_minutes")
            if hold_min is not None:
                total_hold_minutes += hold_min
                hold_count += 1

            conf = trade.get("ai_confidence")
            if conf is not None:
                total_confidence += conf
                confidence_count += 1

            if pnl_pct > best_pnl:
                best_pnl = pnl_pct
                best_trade = {
                    "ticker": trade.get("ticker"),
                    "pnl_pct": pnl_pct,
                    "pnl_amount": pnl_amount,
                }

            if pnl_pct < worst_pnl:
                worst_pnl = pnl_pct
                worst_trade = {
                    "ticker": trade.get("ticker"),
                    "pnl_pct": pnl_pct,
                    "pnl_amount": pnl_amount,
                }

        win_rate = (win_count / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_hold = (total_hold_minutes / hold_count) if hold_count > 0 else 0.0
        avg_conf = (total_confidence / confidence_count) if confidence_count > 0 else 0.0

        return {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "total_pnl_amount": round(total_pnl_amount, 2),
            "avg_hold_minutes": round(avg_hold, 1),
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "avg_confidence": round(avg_conf, 4),
        }

    async def _save_report(self, target_date: str, report: dict[str, Any]) -> None:
        """feedback_reports 테이블에 피드백 보고서를 저장한다.

        Args:
            target_date: YYYY-MM-DD 형식 날짜 문자열.
            report: 저장할 피드백 보고서 딕셔너리.
        """
        parsed_date = target_date if isinstance(target_date, date) else date.fromisoformat(target_date)

        async with get_session() as session:
            record = FeedbackReport(
                id=str(uuid4()),
                report_type="daily",
                report_date=parsed_date,
                content=report,
            )
            session.add(record)

        logger.info("일일 피드백 보고서 저장 완료 | date=%s", target_date)

    async def _generate_rag_docs(
        self, report: dict[str, Any], trades: list[dict[str, Any]]
    ) -> int:
        """피드백 결과에서 RAG 문서를 자동 생성한다.

        Args:
            report: 일일 피드백 보고서.
            trades: 당일 매매 기록 목록.

        Returns:
            생성된 RAG 문서 수.
        """
        try:
            count = await self.rag_updater.update_from_daily(report, trades)
            return count
        except Exception as exc:
            logger.exception("RAG 문서 생성 실패 | date=%s", report.get("date"))
            return 0
