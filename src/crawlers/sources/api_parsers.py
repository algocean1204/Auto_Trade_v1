"""F1 데이터 수집 -- API 소스별 응답 파서 모음이다.

각 API 소스(Finnhub, AlphaVantage, FRED, FearGreed, Finviz,
Stocktwits, DART)의 JSON 응답을 RawArticle 목록으로 변환한다.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from src.crawlers.models import RawArticle


def _ts_to_dt(ts: int | None) -> datetime | None:
    """Unix timestamp를 datetime으로 변환한다."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def _safe_parse_iso(raw: str | None) -> datetime | None:
    """ISO 형식 날짜 문자열을 안전하게 파싱한다."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_finnhub(data: list | dict) -> list[RawArticle]:
    """Finnhub 뉴스 응답을 파싱한다."""
    if not isinstance(data, list):
        return []
    articles: list[RawArticle] = []
    for item in data:
        articles.append(RawArticle(
            title=item.get("headline", ""),
            content=item.get("summary", ""),
            url=item.get("url", ""),
            source="finnhub",
            published_at=_ts_to_dt(item.get("datetime")),
            metadata={"category": item.get("category", "")},
        ))
    return articles


def parse_alphavantage(data: dict) -> list[RawArticle]:
    """AlphaVantage 뉴스 응답을 파싱한다."""
    feed = data.get("feed", [])
    articles: list[RawArticle] = []
    for item in feed:
        articles.append(RawArticle(
            title=item.get("title", ""),
            content=item.get("summary", ""),
            url=item.get("url", ""),
            source="alphavantage",
            published_at=_safe_parse_iso(item.get("time_published")),
            metadata={"sentiment": item.get("overall_sentiment_label", "")},
        ))
    return articles


def parse_fred(data: dict) -> list[RawArticle]:
    """FRED 경제 지표 응답을 파싱한다. 관측값을 기사 형태로 변환한다."""
    observations = data.get("observations", [])
    if not observations:
        return []
    latest = observations[-1]
    return [RawArticle(
        title=f"FRED 경제지표 업데이트: {latest.get('value', 'N/A')}",
        content=f"Date: {latest.get('date')}, Value: {latest.get('value')}",
        url="https://fred.stlouisfed.org",
        source="fred",
        published_at=_safe_parse_iso(latest.get("date")),
        metadata={"data_type": "economic_indicator"},
    )]


def parse_feargreed(data: dict) -> list[RawArticle]:
    """CNN Fear & Greed Index 응답을 파싱한다."""
    score = data.get("fear_and_greed", {}).get("score")
    rating = data.get("fear_and_greed", {}).get("rating", "unknown")
    if score is None:
        return []
    return [RawArticle(
        title=f"Fear & Greed Index: {score:.0f} ({rating})",
        content=f"Current score: {score}, Rating: {rating}",
        url="https://edition.cnn.com/markets/fear-and-greed",
        source="feargreed",
        published_at=datetime.now(tz=timezone.utc),
        metadata={"score": score, "rating": rating},
    )]


def parse_finviz(data: dict | list) -> list[RawArticle]:
    """Finviz 뉴스 응답을 파싱한다."""
    items = data if isinstance(data, list) else data.get("news", [])
    articles: list[RawArticle] = []
    for item in items:
        articles.append(RawArticle(
            title=item.get("title", ""),
            content=item.get("title", ""),
            url=item.get("link", item.get("url", "")),
            source="finviz",
            published_at=_safe_parse_iso(item.get("date")),
        ))
    return articles


def parse_stocktwits(data: dict) -> list[RawArticle]:
    """Stocktwits 트렌딩 응답을 파싱한다."""
    messages = data.get("messages", [])
    articles: list[RawArticle] = []
    for msg in messages:
        articles.append(RawArticle(
            title=msg.get("body", "")[:100],
            content=msg.get("body", ""),
            url=f"https://stocktwits.com/message/{msg.get('id', '')}",
            source="stocktwits",
            published_at=_safe_parse_iso(msg.get("created_at")),
            metadata={"sentiment": msg.get("entities", {}).get("sentiment", {}).get("basic")},
        ))
    return articles


def parse_dart(data: dict) -> list[RawArticle]:
    """DART 공시 응답을 파싱한다."""
    items = data.get("list", [])
    articles: list[RawArticle] = []
    for item in items:
        articles.append(RawArticle(
            title=item.get("report_nm", ""),
            content=f"{item.get('corp_name', '')}: {item.get('report_nm', '')}",
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
            source="dart",
            published_at=_safe_parse_iso(item.get("rcept_dt")),
            language="ko",
        ))
    return articles


# 소스별 파서 매핑이다
PARSERS: dict[str, Callable] = {
    "finnhub": parse_finnhub,
    "alphavantage": parse_alphavantage,
    "fred": parse_fred,
    "feargreed": parse_feargreed,
    "finviz": parse_finviz,
    "stocktwits": parse_stocktwits,
    "dart": parse_dart,
}
