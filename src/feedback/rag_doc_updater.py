"""
RAG 문서 업데이터 - 피드백과 RAG 시스템 간 브릿지.

피드백 리포트를 받아 RAG 문서로 변환하고 라이프사이클을 관리한다:
- 일일 피드백 → RAG 문서 생성 (손실 교훈, 수익 패턴, 기술적 패턴)
- 주간 분석 → 매크로 컨텍스트 RAG 문서 생성
- 오래된 문서 정리 (관련성 낮은 문서 제거)
- 유용한 문서의 관련성 점수 boost
- 시간 경과에 따른 관련성 decay 적용
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from src.db.connection import get_session
from src.db.models import RagDocument
from src.rag.doc_generator import RAGDocGenerator
from src.rag.embedder import BGEEmbedder
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RAGDocUpdater:
    """피드백 시스템과 RAG 시스템 간 브릿지.

    일일/주간 피드백을 받아 RAG 문서를 자동 생성하고 관리한다.
    BGEEmbedder는 싱글톤으로 관리되며, DB 세션은 각 작업별로 생성한다.
    """

    def __init__(self) -> None:
        """RAGDocUpdater 초기화.

        BGEEmbedder는 싱글톤으로 즉시 로드한다.
        DB 세션은 작업별로 get_session()을 통해 생성한다.
        """
        self.embedder = BGEEmbedder.get_instance()
        logger.info("RAGDocUpdater 초기화 완료 | embedder=%s", self.embedder.backend)

    async def update_from_daily(
        self,
        report: dict[str, Any],
        trades: list[dict[str, Any]],
    ) -> int:
        """일일 피드백 리포트에서 RAG 문서를 생성한다.

        DailyFeedback._generate_rag_docs()에서 호출된다.

        생성 규칙:
        1. pnl_pct < -1.0% 손실 거래 → trade_lesson 문서
        2. win_rate > 70% && 3+ 거래 → strategy_rule 문서
        3. 주목할 기술적 패턴 포함 거래 → technical_pattern 문서

        Args:
            report: 일일 피드백 보고서 딕셔너리.
                키: date, summary, analysis, improvements
            trades: 당일 매매 기록 딕셔너리 목록.
                키: ticker, pnl_pct, entry_price, exit_price, exit_reason,
                    ai_signals, market_regime, hold_minutes 등

        Returns:
            생성된 RAG 문서 수.
        """
        async with get_session() as session:
            generator = RAGDocGenerator(session, self.embedder)

            # RAGDocGenerator.generate_from_daily_feedback() 호출
            # summary는 report["summary"]에서 추출하여 daily_feedback dict로 재구성
            daily_feedback = {
                "date": report.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "total_pnl": report.get("summary", {}).get("total_pnl_pct", 0.0),
                "win_rate": report.get("summary", {}).get("win_rate", 0.0),
                "summary": self._extract_summary_text(report),
                "lessons": report.get("improvements", []),
                "market_regime": self._extract_market_regime(trades),
            }

            created_docs = await generator.generate_from_daily_feedback(
                daily_feedback=daily_feedback,
                trades=trades,
            )

            doc_count = len(created_docs)
            logger.info(
                "일일 피드백에서 RAG 문서 생성 완료 | date=%s | 생성문서=%d",
                daily_feedback["date"],
                doc_count,
            )
            return doc_count

    async def update_from_weekly(self, report: dict[str, Any]) -> int:
        """주간 분석 리포트에서 RAG 문서를 생성한다.

        매크로 컨텍스트 문서 및 전략 인사이트 문서를 생성한다.

        생성 규칙:
        1. macro_context 문서 1개 (시장 체제, VIX, 수익률 곡선 등)
        2. 주간 승률 70% 이상 → strategy_rule 문서 추가

        Args:
            report: 주간 분석 보고서 딕셔너리.
                키: start_date, end_date, total_trades, win_rate, total_pnl,
                    market_regime, vix_level, yield_curve, sector_rotation,
                    economic_indicators, analysis, recommendations

        Returns:
            생성된 RAG 문서 수.
        """
        async with get_session() as session:
            generator = RAGDocGenerator(session, self.embedder)
            doc_count = 0

            # 1. Macro context 문서 생성
            regime = report.get("market_regime", "neutral")
            macro_analysis = {
                "vix_level": report.get("vix_level", "N/A"),
                "yield_curve": report.get("yield_curve", "N/A"),
                "sector_rotation": report.get("sector_rotation", "N/A"),
                "economic_indicators": report.get("economic_indicators", "N/A"),
                "summary": self._extract_weekly_summary(report),
            }

            try:
                await generator.update_macro_context(
                    regime=regime,
                    analysis=macro_analysis,
                )
                doc_count += 1
                logger.info("매크로 컨텍스트 문서 생성 완료 | regime=%s", regime)
            except Exception as exc:
                logger.exception("매크로 컨텍스트 문서 생성 실패 | regime=%s", regime)

            # 2. 주간 승률 70% 이상 → strategy_rule 문서
            win_rate = report.get("win_rate", 0.0)
            total_trades = report.get("total_trades", 0)
            if win_rate >= 70.0 and total_trades >= 10:
                try:
                    strategy_doc = await self._create_weekly_strategy_doc(
                        generator, report
                    )
                    if strategy_doc:
                        doc_count += 1
                        logger.info(
                            "주간 전략 룰 문서 생성 완료 | win_rate=%.1f%%",
                            win_rate,
                        )
                except Exception as exc:
                    logger.exception("주간 전략 룰 문서 생성 실패")

            logger.info(
                "주간 분석에서 RAG 문서 생성 완료 | 기간=%s~%s | 생성문서=%d",
                report.get("start_date", "N/A"),
                report.get("end_date", "N/A"),
                doc_count,
            )
            return doc_count

    async def cleanup_old_docs(self, max_age_days: int = 90) -> int:
        """오래된 RAG 문서를 삭제한다.

        max_age_days보다 오래된 문서를 정리한다.
        단, relevance_score >= 0.8인 고관련성 문서는 보존한다.

        정리 대상:
        - ticker_profile (90일 이상)
        - trade_lesson (90일 이상)
        - technical_pattern (90일 이상)
        - macro_context (90일 이상)

        보존 대상:
        - event_playbook (수동 관리)
        - strategy_rule (수동 관리)
        - relevance_score >= 0.8 문서 (모든 타입)

        Args:
            max_age_days: 문서 최대 보존 기간 (일).

        Returns:
            삭제된 문서 수.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        # 정리 대상 문서 타입
        types_to_clean = [
            "ticker_profile",
            "trade_lesson",
            "technical_pattern",
            "macro_context",
        ]

        async with get_session() as session:
            # relevance_score < 0.8이고 오래된 문서만 조회
            stmt = select(RagDocument).where(
                RagDocument.doc_type.in_(types_to_clean),
                RagDocument.created_at < cutoff_date,
                RagDocument.relevance_score < 0.8,
            )
            result = await session.execute(stmt)
            docs_to_delete = result.scalars().all()

            deleted_count = 0
            for doc in docs_to_delete:
                await session.delete(doc)
                deleted_count += 1
                logger.debug(
                    "오래된 RAG 문서 삭제 | id=%s | type=%s | created_at=%s | relevance=%.2f",
                    doc.id,
                    doc.doc_type,
                    doc.created_at.isoformat() if doc.created_at else "N/A",
                    doc.relevance_score,
                )

            logger.info(
                "오래된 RAG 문서 정리 완료 | 기준일=%s | 삭제=%d개",
                cutoff_date.strftime("%Y-%m-%d"),
                deleted_count,
            )
            return deleted_count

    async def boost_relevance(self, doc_id: str, boost: float = 0.1) -> None:
        """문서가 유용했을 때 관련성 점수를 증가시킨다.

        RAG 검색 결과가 실제로 도움이 되었을 때 호출된다.
        관련성 점수는 최대 5.0까지 증가한다.

        Args:
            doc_id: 문서 UUID.
            boost: 증가시킬 점수 (기본 0.1).
        """
        async with get_session() as session:
            stmt = select(RagDocument).where(RagDocument.id == doc_id)
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()

            if doc is None:
                logger.warning("문서를 찾을 수 없음 | doc_id=%s", doc_id)
                return

            old_score = doc.relevance_score
            new_score = min(5.0, old_score + boost)
            doc.relevance_score = new_score
            doc.updated_at = datetime.now(timezone.utc)

            logger.info(
                "문서 관련성 boost 완료 | doc_id=%s | %.2f → %.2f (+%.2f)",
                doc_id,
                old_score,
                new_score,
                boost,
            )

    async def decay_relevance(self, decay_factor: float = 0.95) -> int:
        """모든 RAG 문서에 시간 기반 관련성 감쇠를 적용한다.

        주기적으로 호출하여 오래된 문서의 관련성을 자연스럽게 감소시킨다.
        relevance_score * decay_factor를 적용한다.

        단, 다음 문서는 감쇠 제외:
        - event_playbook (수동 관리)
        - strategy_rule (수동 관리)
        - relevance_score >= 2.0 (매우 유용한 문서)

        Args:
            decay_factor: 감쇠 계수 (기본 0.95, 즉 5% 감소).

        Returns:
            감쇠 적용된 문서 수.
        """
        # 감쇠 제외 타입
        excluded_types = ["event_playbook", "strategy_rule"]

        async with get_session() as session:
            # 감쇠 대상 문서 조회
            stmt = select(RagDocument).where(
                ~RagDocument.doc_type.in_(excluded_types),
                RagDocument.relevance_score < 2.0,
                RagDocument.relevance_score > 0.0,
            )
            result = await session.execute(stmt)
            docs = result.scalars().all()

            updated_count = 0
            for doc in docs:
                old_score = doc.relevance_score
                new_score = max(0.0, old_score * decay_factor)
                doc.relevance_score = new_score
                doc.updated_at = datetime.now(timezone.utc)
                updated_count += 1

                logger.debug(
                    "문서 관련성 감쇠 적용 | id=%s | type=%s | %.3f → %.3f",
                    doc.id,
                    doc.doc_type,
                    old_score,
                    new_score,
                )

            logger.info(
                "RAG 문서 관련성 감쇠 완료 | 감쇠계수=%.2f | 적용문서=%d개",
                decay_factor,
                updated_count,
            )
            return updated_count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_summary_text(report: dict[str, Any]) -> str:
        """피드백 보고서에서 요약 텍스트를 추출한다."""
        analysis = report.get("analysis", {})
        if isinstance(analysis, dict):
            # analysis.summary 또는 analysis.overview 같은 필드 탐색
            for key in ["summary", "overview", "feedback", "conclusion"]:
                if key in analysis and isinstance(analysis[key], str):
                    return analysis[key]

        # 기본값: improvements를 문자열로 결합
        improvements = report.get("improvements", [])
        if improvements:
            return " | ".join(str(imp) for imp in improvements[:5])

        return "No summary available."

    @staticmethod
    def _extract_market_regime(trades: list[dict[str, Any]]) -> str:
        """거래 목록에서 가장 빈번한 market_regime을 추출한다."""
        if not trades:
            return "unknown"

        from collections import Counter
        regimes = [t.get("market_regime", "unknown") for t in trades]
        most_common = Counter(regimes).most_common(1)
        return most_common[0][0] if most_common else "unknown"

    @staticmethod
    def _extract_weekly_summary(report: dict[str, Any]) -> str:
        """주간 리포트에서 요약 텍스트를 추출한다."""
        analysis = report.get("analysis", {})
        if isinstance(analysis, dict):
            for key in ["summary", "overview", "conclusion", "weekly_summary"]:
                if key in analysis and isinstance(analysis[key], str):
                    return analysis[key]

        # 기본값: recommendations를 문자열로 결합
        recommendations = report.get("recommendations", [])
        if recommendations:
            return " | ".join(str(rec) for rec in recommendations[:5])

        return "No weekly summary available."

    async def _create_weekly_strategy_doc(
        self,
        generator: RAGDocGenerator,
        report: dict[str, Any],
    ) -> dict[str, Any] | None:
        """주간 고승률 전략 룰 문서를 생성한다."""
        start_date = report.get("start_date", "N/A")
        end_date = report.get("end_date", "N/A")
        win_rate = report.get("win_rate", 0.0)
        total_pnl = report.get("total_pnl", 0.0)
        total_trades = report.get("total_trades", 0)
        regime = report.get("market_regime", "unknown")

        content_lines = [
            f"주간 기간: {start_date} ~ {end_date}",
            f"승률: {win_rate:.1f}% (총 {total_trades}회 거래)",
            f"총 손익: {total_pnl:.2f}%",
            f"시장 체제: {regime}",
        ]

        # recommendations가 있으면 추가
        recommendations = report.get("recommendations", [])
        if recommendations:
            content_lines.append("\n주요 인사이트:")
            for i, rec in enumerate(recommendations[:5], 1):
                content_lines.append(f"{i}. {rec}")

        # analysis summary가 있으면 추가
        summary = self._extract_weekly_summary(report)
        if summary and summary != "No weekly summary available.":
            content_lines.append(f"\n분석 요약:\n{summary}")

        try:
            doc_id = await generator.manager.create({
                "doc_type": "strategy_rule",
                "title": f"주간 전략 룰: {win_rate:.0f}% 승률 ({start_date}~{end_date})",
                "content": "\n".join(content_lines),
                "source": "weekly_feedback",
                "metadata": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "total_trades": total_trades,
                    "market_regime": regime,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                "relevance_score": 1.2,  # 주간 전략 룰은 초기 관련성 1.2로 시작
            })
            return await generator.manager.get(doc_id)
        except Exception as exc:
            logger.exception("주간 전략 룰 문서 생성 실패")
            return None
