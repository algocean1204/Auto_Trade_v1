"""F2 AI 분석 -- Sonnet 4에이전트를 병렬 실행하여 객관적 분석 결과를 생성한다.

Layer 1: 4에이전트가 독립 병렬로 분석하여 앵커링 편향을 방지한다.
MASTER_ANALYST는 Layer 2(Opus 3+1 팀)로 이동하였다.
"""
from __future__ import annotations

import asyncio
import json
import logging

from src.analysis.models import AnalysisContext
from src.analysis.prompts.prompt_registry import PromptRegistry
from src.common.ai_gateway import AiClient, AiResponse
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Layer 1: 4에이전트 병렬 실행 (MASTER_ANALYST는 Layer 2로 이동)
_AGENT_KEYS: list[str] = [
    "NEWS_ANALYST",
    "MACRO_STRATEGIST",
    "RISK_MANAGER",
    "SHORT_TERM_TRADER",
]


def _build_independent_prompt(context: AnalysisContext) -> str:
    """에이전트에게 전달할 독립 분석 프롬프트를 생성한다.

    앵커링 방지를 위해 이전 에이전트 결과를 포함하지 않는다.
    """
    return (
        f"뉴스 요약: {context.news_summary}\n"
        f"기술 지표: {json.dumps(context.indicators, default=str)}\n"
        f"현재 레짐: {context.regime}\n"
        f"보유 포지션: {json.dumps(context.positions, default=str)}\n"
        f"시장 데이터: {json.dumps(context.market_data, default=str)}\n\n"
        "위 정보를 바탕으로 독립적으로 분석하고 JSON으로 응답하라."
    )


def _parse_agent_output(raw: str) -> dict | None:
    """에이전트 응답을 JSON dict로 파싱한다. 실패 시 None을 반환한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("에이전트 응답 JSON 파싱 실패 — 이번 분석 건너뜀: %s", raw[:200])
        return None


class ComprehensiveTeam:
    """Sonnet 4에이전트를 병렬 실행하여 독립 분석 결과를 생성한다.

    Layer 1: NEWS_ANALYST, MACRO_STRATEGIST, RISK_MANAGER, SHORT_TERM_TRADER
    4에이전트가 동시에 독립 분석하여 앵커링 편향을 방지한다.
    최종 종합 판단은 Layer 2(Opus 3+1 팀)에서 수행한다.
    """

    def __init__(self, ai_client: AiClient) -> None:
        self._ai = ai_client
        self._registry = PromptRegistry()
        logger.info("ComprehensiveTeam 초기화 완료 (%d 에이전트, 병렬)", len(_AGENT_KEYS))

    async def analyze(self, context: AnalysisContext) -> dict[str, str]:
        """4에이전트를 병렬 실행하고 각 에이전트의 분석 텍스트를 반환한다.

        반환: {에이전트키: 분석결과텍스트} dict
        Opus 3+1 팀이 이 결과를 받아 최종 판단을 내린다.
        """
        prompt = _build_independent_prompt(context)

        tasks = [
            self._run_agent(agent_key, prompt)
            for agent_key in _AGENT_KEYS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        reports: dict[str, str] = {}
        for agent_key, result in zip(_AGENT_KEYS, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("에이전트 실패: %s — %s", agent_key, result)
                reports[agent_key] = json.dumps(
                    {"agent": agent_key, "error": str(result)},
                    ensure_ascii=False,
                )
            else:
                reports[agent_key] = result
            logger.info("에이전트 완료: %s", agent_key)

        return reports

    async def _run_agent(
        self,
        agent_key: str,
        prompt: str,
    ) -> str:
        """단일 에이전트를 실행하고 원본 응답 텍스트를 반환한다."""
        system_prompt = self._registry.get(agent_key)
        try:
            response: AiResponse = await self._ai.send_text(
                prompt, system=system_prompt, model="sonnet",
            )
            return response.content
        except Exception:
            logger.exception("에이전트 실행 실패: %s", agent_key)
            raise
