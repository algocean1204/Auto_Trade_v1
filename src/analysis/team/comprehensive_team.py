"""F2 AI 분석 -- 5개 AI 페르소나를 순차 실행하여 종합 보고서를 생성한다."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.analysis.models import AnalysisContext, ComprehensiveReport
from src.analysis.prompts.prompt_registry import PromptRegistry
from src.common.ai_gateway import AiClient, AiResponse
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 5개 에이전트 실행 순서이다
_AGENT_ORDER: list[str] = [
    "NEWS_ANALYST",
    "MACRO_STRATEGIST",
    "RISK_MANAGER",
    "SHORT_TERM_TRADER",
    "MASTER_ANALYST",
]


def _build_agent_prompt(context: AnalysisContext, prior_results: list[dict]) -> str:
    """에이전트에게 전달할 분석 프롬프트를 생성한다."""
    prior_text = json.dumps(prior_results, default=str, ensure_ascii=False)
    return (
        f"뉴스 요약: {context.news_summary}\n"
        f"기술 지표: {json.dumps(context.indicators, default=str)}\n"
        f"현재 레짐: {context.regime}\n"
        f"보유 포지션: {json.dumps(context.positions, default=str)}\n"
        f"시장 데이터: {json.dumps(context.market_data, default=str)}\n"
        f"이전 에이전트 분석: {prior_text}\n\n"
        "위 정보를 바탕으로 분석하고 JSON으로 응답하라."
    )


def _parse_agent_output(raw: str) -> dict:
    """에이전트 응답을 JSON dict로 파싱한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return {"raw_response": raw[:500]}


def _merge_signals(agent_results: list[dict]) -> list[dict]:
    """모든 에이전트의 signals를 병합한다."""
    merged: list[dict] = []
    for result in agent_results:
        signals = result.get("signals", [])
        if isinstance(signals, list):
            merged.extend(signals)
    return merged


def _calculate_confidence(agent_results: list[dict]) -> float:
    """에이전트 결과들의 평균 확신도를 계산한다."""
    confidences: list[float] = []
    for result in agent_results:
        conf = result.get("confidence", 0.5)
        if isinstance(conf, (int, float)):
            confidences.append(float(conf))
    return round(sum(confidences) / max(len(confidences), 1), 3)


def _extract_recommendations(agent_results: list[dict]) -> list[str]:
    """에이전트 결과에서 추천사항을 추출한다."""
    recs: list[str] = []
    for result in agent_results:
        items = result.get("recommendations", result.get("actions", []))
        if isinstance(items, list):
            recs.extend(str(r) for r in items)
    return recs


def _determine_risk_level(agent_results: list[dict]) -> str:
    """RISK_MANAGER 결과에서 위험 수준을 추출한다."""
    for result in agent_results:
        level = result.get("risk_level")
        if level in ("low", "medium", "high", "critical"):
            return level
    return "medium"


class ComprehensiveTeam:
    """5개 AI 페르소나를 순차 실행하여 종합 분석 보고서를 생성한다.

    순서: NEWS_ANALYST -> MACRO_STRATEGIST -> RISK_MANAGER
          -> SHORT_TERM_TRADER -> MASTER_ANALYST
    이전 에이전트 결과가 다음 에이전트에게 컨텍스트로 전달된다.
    """

    def __init__(self, ai_client: AiClient) -> None:
        self._ai = ai_client
        self._registry = PromptRegistry()
        logger.info("ComprehensiveTeam 초기화 완료 (%d 에이전트)", len(_AGENT_ORDER))

    async def analyze(self, context: AnalysisContext) -> ComprehensiveReport:
        """5개 에이전트를 순차 실행하고 결과를 종합한다."""
        agent_results: list[dict] = []

        for agent_key in _AGENT_ORDER:
            result = await self._run_agent(agent_key, context, agent_results)
            agent_results.append(result)
            logger.info("에이전트 완료: %s", agent_key)

        return self._build_report(agent_results, context)

    async def _run_agent(
        self,
        agent_key: str,
        context: AnalysisContext,
        prior_results: list[dict],
    ) -> dict:
        """단일 에이전트를 실행한다."""
        system = self._registry.get(agent_key)
        prompt = _build_agent_prompt(context, prior_results)
        try:
            response: AiResponse = await self._ai.send_text(
                prompt, system=system, model="sonnet",
            )
            parsed = _parse_agent_output(response.content)
            parsed["agent"] = agent_key
            return parsed
        except Exception:
            logger.exception("에이전트 실행 실패: %s", agent_key)
            return {"agent": agent_key, "error": True}

    def _build_report(
        self,
        agent_results: list[dict],
        context: AnalysisContext,
    ) -> ComprehensiveReport:
        """에이전트 결과들을 종합 보고서로 합성한다."""
        return ComprehensiveReport(
            signals=_merge_signals(agent_results),
            confidence=_calculate_confidence(agent_results),
            recommendations=_extract_recommendations(agent_results),
            regime_assessment=context.regime,
            risk_level=_determine_risk_level(agent_results),
            timestamp=datetime.now(tz=timezone.utc),
        )
