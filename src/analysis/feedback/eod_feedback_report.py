"""F2 AI 분석 -- 일일 매매 피드백 보고서를 생성한다."""
from __future__ import annotations

import json
import logging

from src.analysis.models import FeedbackReport
from src.common.ai_gateway import AiClient, AiResponse
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)


def _build_feedback_prompt(
    daily_trades: list[dict],
    pnl_summary: dict,
) -> str:
    """피드백 분석용 프롬프트를 생성한다."""
    trades_json = json.dumps(daily_trades, default=str, ensure_ascii=False)
    pnl_json = json.dumps(pnl_summary, default=str, ensure_ascii=False)
    return (
        "오늘의 매매 내역과 손익을 분석하여 피드백을 작성하라.\n"
        "생존 매매 원칙($300/월)에 비추어 평가하라.\n\n"
        f"매매 내역:\n{trades_json}\n\n"
        f"손익 요약:\n{pnl_json}\n\n"
        "아래 JSON 형식으로 응답하라:\n"
        '{"summary": {"total_trades": int, "win_rate": float, '
        '"total_pnl_amount": float, "best_trade": str, "worst_trade": str}, '
        '"lessons": ["교훈1", "교훈2", ...], '
        '"suggestions": ["개선안1", "개선안2", ...]}'
    )


def _parse_feedback_response(raw: str) -> dict:
    """Claude 피드백 응답을 파싱한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("피드백 응답 파싱 실패: %s", raw[:200])
        return {}


def _build_fallback_report(
    daily_trades: list[dict],
    pnl_summary: dict,
) -> FeedbackReport:
    """AI 분석 실패 시 기본 피드백 보고서를 생성한다."""
    return FeedbackReport(
        summary={
            "total_trades": len(daily_trades),
            "total_pnl_amount": pnl_summary.get("total_pnl_amount", 0.0),
        },
        lessons=["AI 분석 실패로 자동 교훈 추출 불가"],
        suggestions=["수동 매매 일지 검토 권장"],
    )


class EODFeedbackReport:
    """일일 매매 피드백 보고서를 Claude로 생성한다.

    매매 내역과 PnL을 분석하여 교훈/개선안을 추출한다.
    """

    def __init__(self, ai_client: AiClient) -> None:
        self._ai = ai_client
        logger.info("EODFeedbackReport 초기화 완료")

    async def generate(
        self,
        daily_trades: list[dict],
        pnl_summary: dict,
    ) -> FeedbackReport:
        """일일 매매 결과를 분석하여 피드백 보고서를 생성한다."""
        if not daily_trades:
            return self._empty_report()

        prompt = _build_feedback_prompt(daily_trades, pnl_summary)
        try:
            response: AiResponse = await self._ai.send_text(
                prompt, model="sonnet",
            )
            parsed = _parse_feedback_response(response.content)
            if not parsed:
                return _build_fallback_report(daily_trades, pnl_summary)
            report = self._from_parsed(parsed)
            logger.info("피드백 보고서 생성 완료 (%d 교훈)", len(report.lessons))
            return report
        except Exception:
            logger.exception("피드백 보고서 생성 실패")
            return _build_fallback_report(daily_trades, pnl_summary)

    def _from_parsed(self, parsed: dict) -> FeedbackReport:
        """파싱된 dict를 FeedbackReport로 변환한다."""
        return FeedbackReport(
            summary=parsed.get("summary", {}),
            lessons=parsed.get("lessons", []),
            suggestions=parsed.get("suggestions", []),
        )

    def _empty_report(self) -> FeedbackReport:
        """매매 없는 날의 빈 보고서를 반환한다."""
        return FeedbackReport(
            summary={"total_trades": 0, "total_pnl_amount": 0.0},
            lessons=["오늘 매매 없음"],
            suggestions=[],
        )
