"""F2 AI 분석 -- 티커별 종합 프로파일을 생성한다."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.analysis.models import ClassifiedNews, TickerProfile
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)


def _calculate_sentiment(news_list: list[ClassifiedNews]) -> float:
    """뉴스 목록의 가중 평균 감성 점수를 계산한다.

    bullish=+1, neutral=0, bearish=-1, 영향도로 가중한다.
    """
    if not news_list:
        return 0.0

    direction_map: dict[str, float] = {
        "bullish": 1.0,
        "neutral": 0.0,
        "bearish": -1.0,
    }
    total_weight = 0.0
    weighted_sum = 0.0

    for n in news_list:
        weight = n.impact_score
        score = direction_map.get(n.direction, 0.0)
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0.0:
        return 0.0
    return round(weighted_sum / total_weight, 3)


def _filter_ticker_news(
    ticker: str,
    all_news: list[ClassifiedNews],
) -> list[ClassifiedNews]:
    """특정 티커에 관련된 뉴스만 필터링한다."""
    upper_ticker = ticker.upper()
    return [
        n for n in all_news
        if upper_ticker in [t.upper() for t in n.tickers_affected]
    ]


def _summarize_indicators(indicators: dict) -> dict:
    """기술 지표 dict에서 핵심만 요약한다."""
    keys = ["rsi", "vwap", "atr", "obv", "bollinger", "volume"]
    return {k: indicators[k] for k in keys if k in indicators}


def _build_analysis_text(
    ticker: str,
    sentiment: float,
    news_count: int,
    indicators: dict,
) -> str:
    """분석 요약 텍스트를 생성한다."""
    sentiment_label = "강세" if sentiment > 0.3 else "약세" if sentiment < -0.3 else "중립"
    parts: list[str] = [
        f"{ticker}: 감성={sentiment_label}({sentiment:.2f})",
        f"관련뉴스={news_count}건",
    ]
    rsi = indicators.get("rsi")
    if rsi is not None:
        parts.append(f"RSI={rsi}")
    return ", ".join(parts)


class TickerProfiler:
    """티커별 뉴스 감성 + 기술 지표를 종합한 프로파일을 생성한다.

    뉴스 감성은 영향도 가중 평균, 지표는 핵심 항목만 요약한다.
    """

    def __init__(self) -> None:
        logger.info("TickerProfiler 초기화 완료")

    def profile(
        self,
        ticker: str,
        news: list[ClassifiedNews],
        indicators: dict,
    ) -> TickerProfile:
        """티커의 종합 프로파일을 생성한다."""
        related = _filter_ticker_news(ticker, news)
        sentiment = _calculate_sentiment(related)
        summary = _summarize_indicators(indicators)
        text = _build_analysis_text(ticker, sentiment, len(related), summary)

        result = TickerProfile(
            ticker=ticker.upper(),
            news_sentiment=sentiment,
            indicator_summary=summary,
            analysis_text=text,
            timestamp=datetime.now(tz=timezone.utc),
        )
        logger.info("프로파일 생성: %s (감성=%.2f)", ticker, sentiment)
        return result
