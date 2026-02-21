"""종합분석팀 모듈.

1리더 + 3분석관(Opus) 구조로 크롤링된 데이터를 다각도로 분석하여
오늘 장에서 어떤 섹터/종목이 강세(2X 매수)인지 약세(인버스 2X)인지 판단한다.
자동매매 시스템의 참고 자료로 활용된다.

분석관 구성:
  - 분석관 1 (매크로/섹터): 글로벌 매크로 환경 + 섹터 로테이션
  - 분석관 2 (기술적/모멘텀): RSI, MACD, 볼린저밴드, 거래량 패턴
  - 분석관 3 (심리/리스크): 뉴스 센티먼트, Fear & Greed, 위험 요인
  - 리더: 3 분석관 의견을 종합하여 최종 판단

3 분석관은 asyncio.gather로 병렬 호출되며, 리더가 최종 종합한다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import (
    build_comprehensive_eod_report_prompt,
    build_comprehensive_leader_prompt,
    build_comprehensive_macro_prompt,
    build_comprehensive_sentiment_prompt,
    build_comprehensive_technical_prompt,
    get_system_prompt,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_ANALYST_TIMEOUT: float = 120.0         # 개별 분석관 호출 타임아웃 (초)
_EOD_REPORT_MAX_CHARS: int = 1800       # EOD 보고서 최대 문자 수 (텔레그램)
_MAX_ARTICLES_FOR_PROMPT: int = 30      # 프롬프트에 포함할 최대 기사 수


class ComprehensiveAnalysisTeam:
    """종합분석팀.

    3명의 분석관이 각각 다른 관점에서 분석한 뒤,
    리더가 종합하여 최종 섹터/종목 강약 판단을 내린다.
    결과는 자동매매 시스템의 참고 자료로 활용된다.
    """

    def __init__(self, claude_client: ClaudeClient) -> None:
        """ComprehensiveAnalysisTeam을 초기화한다.

        Args:
            claude_client: Claude API 클라이언트 인스턴스.
        """
        self.client = claude_client
        logger.info("ComprehensiveAnalysisTeam 초기화 완료")

    async def analyze_market(
        self,
        classified_articles: list[dict],
        regime: dict,
        tech_indicators: dict,
        positions: list[dict],
        historical_context: str | None,
        fear_greed: float | None,
        vix: float,
    ) -> dict[str, Any]:
        """시장 종합 분석을 수행한다.

        3명의 분석관이 병렬로 분석한 뒤, 리더가 종합하여 최종 판단을 내린다.
        개별 분석관 실패 시에도 나머지 분석관의 결과로 종합을 시도한다.

        Args:
            classified_articles: 분류된 뉴스 기사 목록.
            regime: 현재 시장 레짐 정보 딕셔너리.
            tech_indicators: 종목별 기술적 지표 딕셔너리.
            positions: 현재 보유 포지션 목록.
            historical_context: 과거분석팀의 타임라인 데이터 (있으면).
            fear_greed: CNN Fear & Greed 점수 (0~100, None 가능).
            vix: 현재 VIX 지수.

        Returns:
            종합 분석 결과 딕셔너리. 키 구조:
                session_outlook, confidence, sector_analysis,
                ticker_recommendations, key_risks,
                analyst_opinions, leader_synthesis
        """
        logger.info(
            "종합분석팀 시장 분석 시작 | 기사=%d건, VIX=%.1f, Fear&Greed=%s",
            len(classified_articles),
            vix,
            f"{fear_greed:.1f}" if fear_greed is not None else "N/A",
        )

        # 프롬프트에 포함할 기사 수 제한
        articles_for_prompt = classified_articles[:_MAX_ARTICLES_FOR_PROMPT]

        # Step 1: 3 분석관 병렬 분석
        analyst_tasks = [
            self._macro_analysis(
                articles_for_prompt, regime, vix, fear_greed, historical_context
            ),
            self._technical_analysis(tech_indicators, regime, vix),
            self._sentiment_analysis(articles_for_prompt, fear_greed, positions),
        ]

        analyst_results_raw = await asyncio.gather(
            *analyst_tasks, return_exceptions=True
        )

        # 성공/실패 분류
        analyst_names = ["macro_analyst", "technical_analyst", "sentiment_analyst"]
        analyst_results: list[dict[str, Any]] = []
        analyst_opinions: dict[str, Any] = {}

        for i, (name, result) in enumerate(
            zip(analyst_names, analyst_results_raw)
        ):
            if isinstance(result, Exception):
                logger.error(
                    "종합분석팀 %s 분석 실패: %s", name, result
                )
                fallback = self._get_analyst_fallback(name)
                analyst_results.append(fallback)
                analyst_opinions[name] = {
                    "status": "failed",
                    "error": str(result),
                    "result": fallback,
                }
            else:
                analyst_results.append(result)
                analyst_opinions[name] = {
                    "status": "success",
                    "result": result,
                }

        success_count = sum(
            1 for v in analyst_opinions.values() if v["status"] == "success"
        )
        logger.info(
            "종합분석팀 분석관 완료: %d/3 성공", success_count
        )

        # Step 2: 리더 종합
        try:
            synthesis = await self._leader_synthesis(
                analyst_results, regime, articles_for_prompt, tech_indicators
            )
        except Exception as exc:
            logger.error("종합분석팀 리더 종합 실패: %s", exc)
            synthesis = self._get_leader_fallback(analyst_results)

        # 분석관 의견 추가
        synthesis["analyst_opinions"] = analyst_opinions

        logger.info(
            "종합분석팀 분석 완료 | outlook=%s, confidence=%.2f",
            synthesis.get("session_outlook", "unknown"),
            synthesis.get("confidence", 0.0),
        )

        return synthesis

    async def _macro_analysis(
        self,
        classified_articles: list[dict],
        regime: dict,
        vix: float,
        fear_greed: float | None,
        historical_context: str | None,
    ) -> dict[str, Any]:
        """분석관 1: 매크로/섹터 관점 분석을 수행한다.

        글로벌 매크로 환경, 섹터 로테이션, 지정학 리스크를 분석한다.

        Returns:
            매크로 분석 결과 딕셔너리.
        """
        logger.info("종합분석팀 매크로 분석관 호출...")
        prompt = build_comprehensive_macro_prompt(
            classified_articles=classified_articles,
            regime=regime,
            vix=vix,
            fear_greed=fear_greed,
            historical_context=historical_context,
        )

        result = await self.client.call_json(
            prompt=prompt,
            task_type="comprehensive_macro",
            system_prompt=get_system_prompt("comprehensive_macro"),
            use_cache=False,
        )

        if not isinstance(result, dict):
            result = {"raw": result}

        logger.info(
            "매크로 분석관 완료 | outlook=%s",
            result.get("macro_outlook", "unknown"),
        )
        return result

    async def _technical_analysis(
        self,
        tech_indicators: dict,
        regime: dict,
        vix: float,
    ) -> dict[str, Any]:
        """분석관 2: 기술적/모멘텀 관점 분석을 수행한다.

        RSI, MACD, 볼린저밴드, 거래량 패턴을 분석한다.

        Returns:
            기술적 분석 결과 딕셔너리.
        """
        logger.info("종합분석팀 기술적 분석관 호출...")
        prompt = build_comprehensive_technical_prompt(
            tech_indicators=tech_indicators,
            regime=regime,
            vix=vix,
        )

        result = await self.client.call_json(
            prompt=prompt,
            task_type="comprehensive_technical",
            system_prompt=get_system_prompt("comprehensive_technical"),
            use_cache=False,
        )

        if not isinstance(result, dict):
            result = {"raw": result}

        logger.info(
            "기술적 분석관 완료 | outlook=%s",
            result.get("technical_outlook", "unknown"),
        )
        return result

    async def _sentiment_analysis(
        self,
        classified_articles: list[dict],
        fear_greed: float | None,
        positions: list[dict],
    ) -> dict[str, Any]:
        """분석관 3: 심리/리스크 관점 분석을 수행한다.

        뉴스 센티먼트, Fear & Greed, 위험 요인을 분석한다.

        Returns:
            심리/리스크 분석 결과 딕셔너리.
        """
        logger.info("종합분석팀 심리/리스크 분석관 호출...")
        prompt = build_comprehensive_sentiment_prompt(
            classified_articles=classified_articles,
            fear_greed=fear_greed,
            positions=positions,
        )

        result = await self.client.call_json(
            prompt=prompt,
            task_type="comprehensive_sentiment",
            system_prompt=get_system_prompt("comprehensive_sentiment"),
            use_cache=False,
        )

        if not isinstance(result, dict):
            result = {"raw": result}

        logger.info(
            "심리/리스크 분석관 완료 | outlook=%s",
            result.get("sentiment_outlook", "unknown"),
        )
        return result

    async def _leader_synthesis(
        self,
        analyst_results: list[dict[str, Any]],
        regime: dict,
        classified_articles: list[dict],
        tech_indicators: dict,
    ) -> dict[str, Any]:
        """리더: 3 분석관 의견을 종합하여 최종 판단을 내린다.

        Args:
            analyst_results: [매크로, 기술적, 심리] 3명의 분석관 결과.
            regime: 현재 시장 레짐 정보.
            classified_articles: 분류된 뉴스 기사 목록.
            tech_indicators: 종목별 기술적 지표.

        Returns:
            종합 분석 결과 딕셔너리.
        """
        logger.info("종합분석팀 리더 종합 호출...")
        prompt = build_comprehensive_leader_prompt(
            analyst_results=analyst_results,
            regime=regime,
            classified_articles=classified_articles,
            tech_indicators=tech_indicators,
        )

        result = await self.client.call_json(
            prompt=prompt,
            task_type="comprehensive_leader",
            system_prompt=get_system_prompt("comprehensive_leader"),
            use_cache=False,
        )

        if not isinstance(result, dict):
            result = {"raw": result}

        logger.info(
            "리더 종합 완료 | session_outlook=%s, confidence=%.2f",
            result.get("session_outlook", "unknown"),
            result.get("confidence", 0.0),
        )
        return result

    async def generate_eod_report(
        self,
        today_analysis: dict[str, Any],
        today_decisions: list[dict[str, Any]],
        today_results: dict[str, Any],
        positions: list[dict[str, Any]],
        risk_gate_blocks: list[dict[str, Any]],
    ) -> str:
        """EOD 매매 분석 보고서를 생성한다.

        오늘의 분석이 실제 매매에 어떻게 반영되었는지,
        분석 정확도는 어떤지, 내일 주의할 점은 무엇인지 정리한다.

        Args:
            today_analysis: 오늘 장 시작 전 종합분석팀 분석 결과.
            today_decisions: 오늘 실행된 매매 결정 목록.
            today_results: 오늘 매매 실적 요약.
            positions: 마감 시점 포지션 목록.
            risk_gate_blocks: 리스크 게이트 차단 내역.

        Returns:
            Telegram 전송용 텍스트 보고서 (Markdown).
        """
        logger.info("종합분석팀 EOD 보고서 생성 시작...")

        try:
            prompt = build_comprehensive_eod_report_prompt(
                today_analysis=today_analysis,
                today_decisions=today_decisions,
                today_results=today_results,
                positions=positions,
                risk_gate_blocks=risk_gate_blocks,
            )

            result = await self.client.call(
                prompt=prompt,
                task_type="comprehensive_eod_report",
                system_prompt=get_system_prompt("comprehensive_eod_report"),
                use_cache=False,
            )

            report_text = result.get("content", "")

            # 텔레그램 메시지 길이 제한
            if len(report_text) > _EOD_REPORT_MAX_CHARS:
                report_text = report_text[:_EOD_REPORT_MAX_CHARS] + "\n\n...(이하 생략)"

            logger.info(
                "종합분석팀 EOD 보고서 생성 완료 | 길이=%d자", len(report_text)
            )
            return report_text

        except Exception as exc:
            logger.error("종합분석팀 EOD 보고서 생성 실패: %s", exc)
            return self._get_eod_fallback_report(today_analysis)

    # ------------------------------------------------------------------
    # 폴백 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _get_analyst_fallback(analyst_name: str) -> dict[str, Any]:
        """분석관 실패 시 기본 결과를 반환한다.

        Args:
            analyst_name: 분석관 이름.

        Returns:
            기본 분석 결과 딕셔너리.
        """
        if analyst_name == "macro_analyst":
            return {
                "macro_outlook": "neutral",
                "macro_confidence": 0.3,
                "macro_reasoning": "매크로 분석관 호출 실패. 중립으로 폴백한다.",
                "sector_analysis": [],
                "key_risks": [],
            }
        elif analyst_name == "technical_analyst":
            return {
                "technical_outlook": "neutral",
                "technical_confidence": 0.3,
                "technical_reasoning": "기술적 분석관 호출 실패. 중립으로 폴백한다.",
                "ticker_signals": [],
                "volume_anomalies": [],
            }
        else:  # sentiment_analyst
            return {
                "sentiment_outlook": "neutral",
                "sentiment_confidence": 0.3,
                "sentiment_reasoning": "심리/리스크 분석관 호출 실패. 중립으로 폴백한다.",
                "news_sentiment": {
                    "bullish_ratio": 0.33,
                    "bearish_ratio": 0.33,
                    "neutral_ratio": 0.34,
                    "tone_shift": "stable",
                },
                "risk_factors": [],
                "contrarian_signals": [],
            }

    @staticmethod
    def _get_leader_fallback(analyst_results: list[dict]) -> dict[str, Any]:
        """리더 종합 실패 시 분석관 결과로 기본 종합을 생성한다.

        Args:
            analyst_results: 3명의 분석관 결과 리스트.

        Returns:
            기본 종합 결과 딕셔너리.
        """
        # 분석관 outlook 추출
        outlooks = []
        for r in analyst_results:
            for key in ("macro_outlook", "technical_outlook", "sentiment_outlook"):
                if key in r:
                    outlooks.append(r[key])

        # 다수결로 결정
        bullish_count = sum(1 for o in outlooks if o == "bullish")
        bearish_count = sum(1 for o in outlooks if o == "bearish")

        if bullish_count > bearish_count:
            session_outlook = "bullish"
        elif bearish_count > bullish_count:
            session_outlook = "bearish"
        else:
            session_outlook = "neutral"

        return {
            "session_outlook": session_outlook,
            "confidence": 0.4,
            "sector_analysis": [],
            "ticker_recommendations": [],
            "key_risks": ["리더 종합 실패로 인한 불확실성 증가"],
            "leader_synthesis": (
                "리더 종합 호출이 실패하여 분석관 다수결로 폴백한다. "
                f"3명 중 bullish {bullish_count}, bearish {bearish_count}, "
                f"neutral {3 - bullish_count - bearish_count}. "
                "확신도가 낮으므로 보수적 운용을 권장한다."
            ),
        }

    @staticmethod
    def _get_eod_fallback_report(today_analysis: dict[str, Any]) -> str:
        """EOD 보고서 생성 실패 시 폴백 보고서를 반환한다.

        Args:
            today_analysis: 오늘의 종합 분석 결과.

        Returns:
            폴백 보고서 텍스트.
        """
        outlook = today_analysis.get("session_outlook", "N/A")
        confidence = today_analysis.get("confidence", 0.0)

        return (
            "*종합분석팀 EOD 보고서*\n\n"
            "EOD 보고서 AI 생성에 실패하여 간략 요약을 제공합니다.\n\n"
            f"장 전 전망: {outlook} (확신도 {confidence:.0%})\n"
            "상세 분석 보고서 생성에 실패하였습니다. "
            "로그를 확인하시기 바랍니다."
        )
