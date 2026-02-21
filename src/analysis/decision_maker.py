"""
매매 판단기 (핵심 모듈)

뉴스 신호 + RAG 컨텍스트 + 기술적 지표 + 시장 레짐을 종합하여
Claude Opus로 최종 매매 판단을 수행한다.

가중치: 뉴스 50% / 시장 레짐+매크로 30% / 기술적 지표 20%
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import build_trading_decision_prompt, get_system_prompt
from src.indicators.aggregator import IndicatorAggregator
from src.rag.retriever import RAGRetriever
from src.strategy.params import MIN_CONFIDENCE, MAX_POSITION_PCT
from src.utils.logger import get_logger
from src.utils.ticker_mapping import get_analysis_ticker

logger = get_logger(__name__)

# 판단 결과 필수 필드
_REQUIRED_DECISION_FIELDS = frozenset({
    "action", "ticker", "confidence",
})

# 허용 action 값
_VALID_ACTIONS = frozenset({"buy", "sell", "hold", "close"})

# 허용 direction 값
_VALID_DIRECTIONS = frozenset({"long", "short"})

# 허용 time_horizon 값
_VALID_TIME_HORIZONS = frozenset({"intraday", "swing"})


class DecisionMaker:
    """매매 판단기.

    뉴스 신호, RAG 과거 사례, 기술적 지표, 시장 레짐을
    종합하여 Claude Opus에 판단을 요청하고,
    응답을 파싱 및 검증하여 실행 가능한 매매 명령 목록을 반환한다.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        rag_retriever: RAGRetriever,
        indicator_aggregator: IndicatorAggregator,
    ) -> None:
        """DecisionMaker 초기화.

        Args:
            claude_client: Claude API 클라이언트.
            rag_retriever: RAG 검색기.
            indicator_aggregator: 기술적 지표 종합기.
        """
        self.client = claude_client
        self.rag = rag_retriever
        self.indicators = indicator_aggregator
        logger.info("DecisionMaker 초기화 완료")

    async def make_decision(
        self,
        classified_signals: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        regime: str,
        price_data: dict[str, pd.DataFrame],
        crawl_context: str = "",
        profit_context: dict[str, Any] | None = None,
        risk_context: dict[str, Any] | None = None,
        comprehensive_analysis: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """매매 판단을 수행한다.

        1. 관련 종목 추출
        2. RAG 컨텍스트 생성 (과거 유사 사례 검색)
        3. 관련 종목 기술적 지표 종합
        4. Claude Opus에 종합 프롬프트 전송
        5. 응답 파싱 + 검증

        Args:
            classified_signals: 분류된 뉴스 신호 목록.
            positions: 현재 보유 포지션 목록.
                각 항목: ``{"ticker", "direction", "quantity", "entry_price", "unrealized_pnl", ...}``
            regime: 현재 시장 레짐 문자열.
            price_data: 종목별 가격 DataFrame 딕셔너리.
                키: 티커, 값: OHLCV DataFrame.
            crawl_context: AI 컨텍스트 빌더가 생성한 실시간 시장 컨텍스트 문자열.
            profit_context: 수익 목표 컨텍스트 (Addendum 25).
            risk_context: 리스크 게이트 컨텍스트 (Addendum 26).
            comprehensive_analysis: 종합분석팀 분석 결과 (참고용, 100% 신뢰 불가).

        Returns:
            매매 판단 목록. 각 항목:
                - action: "buy" | "sell" | "hold" | "close"
                - ticker: str
                - direction: "long" | "short"
                - confidence: float (0.0 ~ 1.0)
                - reason: str
                - weight_pct: float (자산 대비 비율)
                - take_profit_pct: float
                - stop_loss_pct: float
                - time_horizon: "intraday" | "swing"
        """
        logger.info(
            "매매 판단 시작: 신호 %d건, 포지션 %d건, 레짐=%s",
            len(classified_signals), len(positions), regime,
        )

        # 1. 관련 종목 추출
        tickers = self._extract_relevant_tickers(classified_signals, positions)
        logger.info("관련 종목: %s", tickers)

        # 2, 3을 병렬 수행: RAG 컨텍스트 + 기술적 지표
        rag_task = self.rag.build_context(
            signals=classified_signals,
            positions=positions,
        )
        indicator_task = self._build_indicator_summary(tickers, price_data)

        rag_context, tech_indicators = await asyncio.gather(
            rag_task, indicator_task,
        )

        logger.info(
            "RAG 컨텍스트 길이: %d, 기술적 지표 종목 수: %d",
            len(rag_context), len(tech_indicators),
        )

        # 3.5 종목별 프로필 조회 (RAG ticker_profile)
        ticker_profiles: dict[str, str] = {}
        for ticker in tickers:
            try:
                results = await self.rag.search(
                    query=f"{ticker} 종목 특성 매매 주의사항",
                    ticker=ticker,
                    doc_types=["ticker_profile"],
                    top_k=1,
                    min_similarity=0.1,
                )
                if results:
                    ticker_profiles[ticker] = results[0].get("content", "")
            except Exception as profile_exc:
                logger.debug("프로필 조회 실패 (%s): %s", ticker, profile_exc)

        if ticker_profiles:
            logger.info("종목 프로필 주입: %d건 (%s)", len(ticker_profiles), list(ticker_profiles.keys()))

        # 3.6 CNN Fear&Greed 실시간 조회 (1분 캐시, 실패 시 None으로 대체)
        fear_greed_data: dict[str, Any] | None = None
        try:
            from src.monitoring.fred_client import fetch_cnn_fear_greed
            fear_greed_data = await fetch_cnn_fear_greed()
            logger.info(
                "Fear&Greed 주입: score=%s (%s), source=%s",
                fear_greed_data.get("score"),
                fear_greed_data.get("label"),
                fear_greed_data.get("source"),
            )
        except Exception as fg_exc:
            logger.warning("Fear&Greed 조회 실패, 프롬프트에서 생략: %s", fg_exc)

        # 4. Claude Opus 프롬프트 생성 및 호출
        prompt = build_trading_decision_prompt(
            signals=classified_signals,
            positions=positions,
            rag_context=rag_context,
            regime=regime,
            tech_indicators=tech_indicators,
            crawl_context=crawl_context,
            profit_context=profit_context,
            risk_context=risk_context,
            ticker_profiles=ticker_profiles if ticker_profiles else None,
            fear_greed=fear_greed_data,
            comprehensive_analysis=comprehensive_analysis,
        )

        raw_decisions = await self.client.call_json(
            prompt=prompt,
            task_type="trading_decision",
            system_prompt=get_system_prompt("trading_decision"),
            max_tokens=8192,
            use_cache=False,  # 매매 판단은 항상 최신 데이터 기반
        )

        # 5. 응답 파싱 + 검증
        if not isinstance(raw_decisions, list):
            logger.warning("Claude 응답이 배열이 아닙니다: %s", type(raw_decisions))
            raw_decisions = [raw_decisions] if isinstance(raw_decisions, dict) else []

        validated = self._validate_decisions(raw_decisions)

        logger.info(
            "매매 판단 완료: 원본 %d건 -> 유효 %d건",
            len(raw_decisions), len(validated),
        )
        return validated

    async def _build_indicator_summary(
        self,
        tickers: list[str],
        price_data: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        """관련 종목들의 기술적 지표를 종합한다.

        각 종목에 대해 IndicatorAggregator.aggregate를 호출하고,
        composite_score와 direction을 추출하여 요약 딕셔너리를 생성한다.

        Args:
            tickers: 분석 대상 종목 목록.
            price_data: 종목별 OHLCV DataFrame 딕셔너리.

        Returns:
            종목별 기술적 지표 요약 딕셔너리.
        """
        summary: dict[str, Any] = {}

        tasks = []
        valid_tickers = []
        for ticker in tickers:
            # 레버리지 ETF인 경우 본주 데이터로 기술적 분석을 수행한다.
            analysis_ticker = get_analysis_ticker(ticker)
            df = price_data.get(analysis_ticker)
            if df is None:
                df = price_data.get(ticker)
            if df is None or df.empty:
                logger.warning("가격 데이터 없음: ticker=%s, analysis_ticker=%s", ticker, analysis_ticker)
                summary[ticker] = {
                    "composite_score": 0.0,
                    "direction": "neutral",
                    "confidence": 0.0,
                    "signals": [],
                    "analysis_ticker": analysis_ticker,
                }
                continue
            valid_tickers.append((ticker, analysis_ticker))
            tasks.append(self.indicators.aggregate(ticker=analysis_ticker, price_df=df))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for (ticker, analysis_ticker), result in zip(valid_tickers, results):
                if isinstance(result, Exception):
                    logger.error("지표 종합 실패: %s -> %s", ticker, result)
                    summary[ticker] = {
                        "composite_score": 0.0,
                        "direction": "neutral",
                        "confidence": 0.0,
                        "signals": [],
                        "analysis_ticker": analysis_ticker,
                    }
                else:
                    summary[ticker] = {
                        "composite_score": result.get("composite_score", 0.0),
                        "direction": result.get("direction", "neutral"),
                        "confidence": result.get("confidence", 0.0),
                        "signals": [
                            {
                                "indicator": s["indicator"],
                                "contribution": s["contribution"],
                                "contextual_signal": {
                                    "direction": s["contextual_signal"].get("direction", "neutral"),
                                    "strength": s["contextual_signal"].get("strength", "weak"),
                                    "reason": s["contextual_signal"].get("reason", ""),
                                },
                            }
                            for s in result.get("signals", [])
                        ],
                        "analysis_ticker": analysis_ticker,
                    }

        return summary

    def _validate_decisions(self, decisions: list[Any]) -> list[dict[str, Any]]:
        """판단 결과 목록을 검증하고 정제한다.

        필수 필드 존재 여부, confidence 범위, action/direction 유효성 등을 검사한다.
        confidence가 MIN_CONFIDENCE 미만인 항목은 제외한다.
        weight_pct가 MAX_POSITION_PCT를 초과하면 클램프한다.

        Args:
            decisions: Claude가 반환한 판단 결과 목록.

        Returns:
            검증을 통과한 판단 결과 목록.
        """
        validated: list[dict[str, Any]] = []

        for item in decisions:
            if not isinstance(item, dict):
                logger.warning("판단 결과가 딕셔너리가 아닙니다: %s", type(item))
                continue

            # 필수 필드 확인
            missing = _REQUIRED_DECISION_FIELDS - set(item.keys())
            if missing:
                logger.warning("판단 결과 필수 필드 누락: %s", missing)
                continue

            # action 검증
            action = str(item.get("action", "")).lower()
            if action not in _VALID_ACTIONS:
                logger.warning("유효하지 않은 action: %s", action)
                continue

            # confidence 검증
            try:
                confidence = float(item.get("confidence", 0.0))
            except (ValueError, TypeError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))

            # hold는 confidence 체크 없이 통과
            if action != "hold" and confidence < MIN_CONFIDENCE:
                logger.info(
                    "신뢰도 부족으로 제외: ticker=%s, action=%s, confidence=%.2f (최소 %.2f)",
                    item.get("ticker"), action, confidence, MIN_CONFIDENCE,
                )
                continue

            # direction 검증
            direction = str(item.get("direction", "long")).lower()
            if direction not in _VALID_DIRECTIONS:
                direction = "long"

            # weight_pct 검증 및 클램프
            try:
                weight_pct = float(item.get("weight_pct", 10.0))
            except (ValueError, TypeError):
                weight_pct = 10.0
            weight_pct = max(0.0, min(MAX_POSITION_PCT, weight_pct))

            # stop_loss_pct, take_profit_pct 검증
            try:
                stop_loss_pct = float(item.get("stop_loss_pct", 3.0))
            except (ValueError, TypeError):
                stop_loss_pct = 3.0

            try:
                take_profit_pct = float(item.get("take_profit_pct", 6.0))
            except (ValueError, TypeError):
                take_profit_pct = 6.0

            # time_horizon 검증
            time_horizon = str(item.get("time_horizon", "intraday")).lower()
            if time_horizon not in _VALID_TIME_HORIZONS:
                time_horizon = "intraday"

            validated.append({
                "action": action,
                "ticker": str(item["ticker"]).upper(),
                "direction": direction,
                "confidence": round(confidence, 4),
                "reason": str(item.get("reason", "")),
                "weight_pct": round(weight_pct, 2),
                "take_profit_pct": round(take_profit_pct, 2),
                "stop_loss_pct": round(stop_loss_pct, 2),
                "time_horizon": time_horizon,
            })

        return validated

    @staticmethod
    def _extract_relevant_tickers(
        signals: list[dict[str, Any]],
        positions: list[dict[str, Any]],
    ) -> list[str]:
        """신호와 포지션에서 관련 종목을 중복 없이 추출한다.

        Args:
            signals: 분류된 뉴스 신호 목록.
            positions: 현재 보유 포지션 목록.

        Returns:
            중복 제거된 종목 티커 목록.
        """
        tickers: set[str] = set()

        for signal in signals:
            # tickers 필드가 리스트인 경우
            for t in signal.get("tickers", []):
                if isinstance(t, str) and t.strip():
                    tickers.add(t.upper())
            # 단일 ticker 필드인 경우
            if ticker := signal.get("ticker"):
                if isinstance(ticker, str) and ticker.strip():
                    tickers.add(ticker.upper())

        for position in positions:
            if ticker := position.get("ticker"):
                if isinstance(ticker, str) and ticker.strip():
                    tickers.add(ticker.upper())

        return sorted(tickers)
