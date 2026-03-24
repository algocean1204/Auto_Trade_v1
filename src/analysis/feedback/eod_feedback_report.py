"""F2 AI 분석 -- 일일 매매 피드백 보고서를 생성한다."""
from __future__ import annotations

import json
import logging

from src.analysis.models import FeedbackReport
from src.common.ai_gateway import AiClient, AiResponse
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)


async def _load_previous_feedback(cache: object) -> list[str]:
    """전날 피드백의 suggestions를 캐시에서 로드한다."""
    try:
        data = await cache.read_json("feedback:latest")  # type: ignore[union-attr]
        if data and isinstance(data, dict):
            return data.get("suggestions", [])
    except Exception as exc:
        logger.debug("전날 피드백 캐시 로드 실패 (무시): %s", exc)
    return []


def _build_feedback_prompt(
    daily_trades: list[dict],
    pnl_summary: dict,
    previous_suggestions: list[str] | None = None,
) -> str:
    """피드백 분석용 프롬프트를 생성한다."""
    trades_json = json.dumps(daily_trades, default=str, ensure_ascii=False)
    pnl_json = json.dumps(pnl_summary, default=str, ensure_ascii=False)

    prev_section = ""
    if previous_suggestions:
        prev_lines = "\n".join(f"  - {s}" for s in previous_suggestions)
        prev_section = (
            f"\n전일 개선안:\n{prev_lines}\n"
            "위 개선안이 오늘 매매에 반영되었는지 분석하고, "
            "'feedback_status' 필드에 각 항목의 반영 여부와 이유를 포함하라.\n"
        )

    return (
        "오늘의 매매 내역과 손익을 분석하여 피드백을 작성하라.\n"
        "생존 매매 원칙($300/월)에 비추어 평가하라.\n\n"
        f"매매 내역:\n{trades_json}\n\n"
        f"손익 요약:\n{pnl_json}\n"
        f"{prev_section}\n"
        "아래 JSON 형식으로 응답하라:\n"
        '{"summary": {"total_trades": int, "win_rate": float, '
        '"total_pnl_amount": float, "best_trade": str, "worst_trade": str}, '
        '"lessons": ["교훈1", "교훈2", ...], '
        '"suggestions": ["개선안1", "개선안2", ...], '
        '"feedback_status": [{"suggestion": "개선안 원문", "reflected": true/false, "reason": "반영/미반영 이유"}]}'
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
        cache: object = None,
    ) -> FeedbackReport:
        """일일 매매 결과를 분석하여 피드백 보고서를 생성한다."""
        if not daily_trades:
            return self._empty_report()

        # 전날 피드백 suggestions를 로드하여 반영 여부를 추적한다
        previous_suggestions: list[str] = []
        if cache is not None:
            previous_suggestions = await _load_previous_feedback(cache)

        prompt = _build_feedback_prompt(daily_trades, pnl_summary, previous_suggestions)
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
