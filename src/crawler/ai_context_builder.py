"""
AI 컨텍스트 빌더.

크롤링 결과를 Claude 프롬프트에 주입할 자연어 컨텍스트로 변환한다.
각 데이터 유형별로 구조화된 섹션을 생성하여 AI 판단의 정확도를 높인다.

생성되는 컨텍스트 섹션:
  - [MARKET SENTIMENT]: CNN Fear & Greed 지수 및 등급
  - [PREDICTION MARKETS]: Polymarket 상위 시장
  - [FED OUTLOOK]: Kalshi 금리 인하 확률
  - [INSIDER ALERT]: 주요 내부자 매도 건수
  - [ECONOMIC CALENDAR]: 오늘의 고영향 경제 이벤트
  - [INDEX SNAPSHOT]: SOX/NDX/SPX 지수 동향
  - [NEWS SUMMARY]: Finviz/StockNow 주요 뉴스 요약
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_ai_context(crawl_results: list[dict[str, Any]]) -> str:
    """크롤링 결과를 AI 프롬프트용 자연어 컨텍스트로 변환한다.

    각 기사의 metadata.data_type을 기준으로 분류하고,
    섹션별로 구조화된 텍스트를 생성한다.

    Args:
        crawl_results: 크롤러에서 수집한 기사/데이터 딕셔너리 목록.

    Returns:
        Claude 프롬프트에 주입할 자연어 컨텍스트 문자열.
    """
    sections: list[str] = []

    # 데이터 유형별 분류
    classified = _classify_results(crawl_results)

    # 1. 시장 심리 (Fear & Greed)
    fear_greed = classified.get("fear_greed_index", [])
    if fear_greed:
        sections.append(_build_sentiment_section(fear_greed))

    # 2. 예측 시장 (Polymarket)
    prediction_markets = classified.get("prediction_market", [])
    if prediction_markets:
        sections.append(_build_prediction_section(prediction_markets))

    # 3. Fed 전망 (Kalshi macro context)
    macro_context = classified.get("macro_context", [])
    if macro_context:
        sections.append(_build_fed_section(macro_context))

    # 4. 내부자 거래 경고
    insider_trades = classified.get("insider_trade", [])
    if insider_trades:
        sections.append(_build_insider_section(insider_trades))

    # 5. 경제 캘린더
    calendar_events = classified.get("economic_calendar", [])
    if calendar_events:
        sections.append(_build_calendar_section(calendar_events))

    # 6. 지수 스냅샷
    index_data = classified.get("index_historical", [])
    if index_data:
        sections.append(_build_index_section(index_data))

    # 7. 뉴스 요약
    news = classified.get("news", [])
    screener = classified.get("screener", [])
    if news or screener:
        sections.append(_build_news_section(news, screener))

    if not sections:
        return "[CRAWL DATA] 수집된 크롤링 데이터 없음.\n"

    header = (
        f"=== AI Trading Context (Generated at "
        f"{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}) ===\n"
    )

    return header + "\n\n".join(sections) + "\n=== End Context ===\n"


def build_ai_context_compact(crawl_results: list[dict[str, Any]]) -> str:
    """토큰 절약을 위한 압축 버전 컨텍스트를 생성한다.

    핵심 지표만 한 줄씩 요약하여 프롬프트 토큰 사용을 최소화한다.

    Args:
        crawl_results: 크롤러에서 수집한 기사/데이터 딕셔너리 목록.

    Returns:
        압축된 자연어 컨텍스트 문자열.
    """
    classified = _classify_results(crawl_results)
    lines: list[str] = ["[MARKET CONTEXT]"]

    # Fear & Greed
    for item in classified.get("fear_greed_index", []):
        meta = item.get("metadata", {})
        score = meta.get("score", "N/A")
        rating = meta.get("rating", "N/A")
        signal = meta.get("signal", {})
        sig_name = signal.get("signal", "NEUTRAL") if isinstance(signal, dict) else "NEUTRAL"
        lines.append(f"Fear&Greed: {score} ({rating}) -> {sig_name}")

    # 예측 시장 (상위 3개)
    pred_markets = classified.get("prediction_market", [])
    polymarkets = [
        p for p in pred_markets
        if p.get("metadata", {}).get("platform") == "polymarket"
    ]
    polymarkets.sort(
        key=lambda x: x.get("metadata", {}).get("volume_24h", 0),
        reverse=True,
    )
    for item in polymarkets[:3]:
        meta = item.get("metadata", {})
        q = meta.get("question", "?")[:60]
        prob = meta.get("yes_probability", 0)
        lines.append(f"Polymarket: {q} -> Yes {prob:.0%}")

    # Kalshi Fed 전망
    for item in classified.get("macro_context", []):
        meta = item.get("metadata", {})
        fed_prob = meta.get("fed_rate_cut_probability")
        if fed_prob is not None:
            lines.append(f"Fed Rate Cut Prob: {fed_prob:.1%}")
        cpi = meta.get("cpi_direction")
        if cpi and isinstance(cpi, dict):
            lines.append(
                f"CPI: {cpi.get('market', '?')[:40]} -> "
                f"Yes {cpi.get('probability', 0):.0%}"
            )

    # 내부자 거래
    insider_trades = classified.get("insider_trade", [])
    if insider_trades:
        sell_count = sum(
            1 for t in insider_trades
            if "sale" in t.get("metadata", {}).get("transaction_type", "").lower()
        )
        lines.append(f"Insider Sales: {sell_count} trades detected")

    # 경제 캘린더
    for item in classified.get("economic_calendar", [])[:3]:
        meta = item.get("metadata", {})
        name = meta.get("event_name", "?")[:40]
        importance = meta.get("importance", 0)
        lines.append(f"Econ: {name} ({'*' * importance})")

    # 지수 스냅샷
    for item in classified.get("index_historical", []):
        meta = item.get("metadata", {})
        symbol = meta.get("symbol", "?")
        close = meta.get("latest_close", 0)
        change = meta.get("change_7d_pct", 0)
        lines.append(f"{symbol}: {close:,.1f} ({change:+.1f}% 7d)")

    if len(lines) == 1:
        lines.append("No crawl data available.")

    return "\n".join(lines)


def _classify_results(
    crawl_results: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """크롤링 결과를 data_type별로 분류한다."""
    classified: dict[str, list[dict[str, Any]]] = {}

    for item in crawl_results:
        metadata = item.get("metadata", {})
        data_type = metadata.get("data_type", "unknown")
        if data_type not in classified:
            classified[data_type] = []
        classified[data_type].append(item)

    return classified


def _build_sentiment_section(items: list[dict[str, Any]]) -> str:
    """[MARKET SENTIMENT] 섹션을 생성한다."""
    lines = ["[MARKET SENTIMENT]"]

    for item in items:
        meta = item.get("metadata", {})
        score = meta.get("score", "N/A")
        rating = meta.get("rating", "N/A")
        prev_close = meta.get("previous_close", "N/A")
        week_ago = meta.get("one_week_ago", "N/A")
        month_ago = meta.get("one_month_ago", "N/A")
        daily_change = meta.get("daily_change", 0)

        signal = meta.get("signal", {})
        signal_name = signal.get("signal", "NEUTRAL") if isinstance(signal, dict) else "NEUTRAL"
        signal_reason = signal.get("reason", "") if isinstance(signal, dict) else ""

        lines.append(
            f"CNN Fear & Greed Index: {score} ({rating})\n"
            f"  Previous Close: {prev_close} | 1W Ago: {week_ago} | "
            f"1M Ago: {month_ago}\n"
            f"  Daily Change: {daily_change:+.1f}\n"
            f"  Signal: {signal_name}\n"
            f"  Reason: {signal_reason}"
        )

    return "\n".join(lines)


def _build_prediction_section(items: list[dict[str, Any]]) -> str:
    """[PREDICTION MARKETS] 섹션을 생성한다."""
    lines = ["[PREDICTION MARKETS]"]

    # Polymarket과 Kalshi 분리
    polymarket = [
        i for i in items
        if i.get("metadata", {}).get("platform") == "polymarket"
    ]
    kalshi = [
        i for i in items
        if i.get("metadata", {}).get("platform") == "kalshi"
    ]

    # Polymarket 상위 3개 (거래량 기준)
    polymarket.sort(
        key=lambda x: x.get("metadata", {}).get("volume_24h", 0),
        reverse=True,
    )
    if polymarket:
        lines.append("Polymarket (Top 3 by 24h volume):")
        for item in polymarket[:3]:
            meta = item.get("metadata", {})
            question = meta.get("question", "Unknown")[:80]
            yes_prob = meta.get("yes_probability", 0)
            volume = meta.get("volume_24h", 0)
            lines.append(
                f"  - {question}\n"
                f"    Yes: {yes_prob:.1%} | 24h Vol: ${volume:,.0f}"
            )

    # Kalshi 주요 시장
    if kalshi:
        lines.append("Kalshi (Macro predictions):")
        for item in kalshi[:5]:
            meta = item.get("metadata", {})
            series = meta.get("series_ticker", "")
            title = meta.get("title", "Unknown")[:60]
            yes_prob = meta.get("yes_probability", 0)
            lines.append(
                f"  - [{series}] {title}: Yes {yes_prob:.1%}"
            )

    return "\n".join(lines)


def _build_fed_section(items: list[dict[str, Any]]) -> str:
    """[FED OUTLOOK] 섹션을 생성한다."""
    lines = ["[FED OUTLOOK]"]

    for item in items:
        meta = item.get("metadata", {})
        fed_prob = meta.get("fed_rate_cut_probability")
        summary = meta.get("summary", "")

        if fed_prob is not None:
            lines.append(f"Fed Rate Cut Probability: {fed_prob:.1%}")

        cpi = meta.get("cpi_direction")
        if cpi and isinstance(cpi, dict):
            lines.append(
                f"CPI Direction: {cpi.get('market', 'N/A')} "
                f"(Yes {cpi.get('probability', 0):.1%})"
            )

        gdp = meta.get("gdp_outlook")
        if gdp and isinstance(gdp, dict):
            lines.append(
                f"GDP Outlook: {gdp.get('market', 'N/A')} "
                f"(Yes {gdp.get('probability', 0):.1%})"
            )

        emp = meta.get("employment_outlook")
        if emp and isinstance(emp, dict):
            lines.append(
                f"Employment: {emp.get('market', 'N/A')} "
                f"(Yes {emp.get('probability', 0):.1%})"
            )

        if summary:
            lines.append(f"Summary: {summary}")

    return "\n".join(lines)


def _build_insider_section(items: list[dict[str, Any]]) -> str:
    """[INSIDER ALERT] 섹션을 생성한다."""
    lines = ["[INSIDER ALERT]"]

    # 거래 유형별 집계
    sells: list[dict[str, Any]] = []
    buys: list[dict[str, Any]] = []

    for item in items:
        meta = item.get("metadata", {})
        tx_type = meta.get("transaction_type", "").lower()
        if "sale" in tx_type or "sell" in tx_type:
            sells.append(meta)
        elif "buy" in tx_type or "purchase" in tx_type:
            buys.append(meta)

    lines.append(
        f"Total: {len(items)} trades "
        f"(Sells: {len(sells)}, Buys: {len(buys)})"
    )

    if sells:
        lines.append("Significant Sales:")
        # 티커별 매도 집계
        sells_by_ticker: dict[str, int] = {}
        for s in sells:
            ticker = s.get("ticker", "?")
            sells_by_ticker[ticker] = sells_by_ticker.get(ticker, 0) + 1
        for ticker, count in sorted(
            sells_by_ticker.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"  - {ticker}: {count} sell transaction(s)")

    if buys:
        lines.append("Notable Buys:")
        buys_by_ticker: dict[str, int] = {}
        for b in buys:
            ticker = b.get("ticker", "?")
            buys_by_ticker[ticker] = buys_by_ticker.get(ticker, 0) + 1
        for ticker, count in sorted(
            buys_by_ticker.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"  - {ticker}: {count} buy transaction(s)")

    return "\n".join(lines)


def _build_calendar_section(items: list[dict[str, Any]]) -> str:
    """[ECONOMIC CALENDAR] 섹션을 생성한다."""
    lines = ["[ECONOMIC CALENDAR]"]

    # importance 기준 정렬 (높은 것 우선)
    sorted_items = sorted(
        items,
        key=lambda x: x.get("metadata", {}).get("importance", 0),
        reverse=True,
    )

    for item in sorted_items[:10]:
        meta = item.get("metadata", {})
        event = meta.get("event_name", "Unknown")
        importance = meta.get("importance", 0)
        country = meta.get("country", "US")
        time_str = meta.get("time", "")
        actual = meta.get("actual", "")
        forecast = meta.get("forecast", "")
        previous = meta.get("previous", "")

        impact_str = "*" * importance if importance else "?"
        values_parts = []
        if actual:
            values_parts.append(f"Act: {actual}")
        if forecast:
            values_parts.append(f"Fcst: {forecast}")
        if previous:
            values_parts.append(f"Prev: {previous}")
        values_str = " | ".join(values_parts) if values_parts else "Pending"

        lines.append(
            f"  [{impact_str}] {country} {event}"
            f"{(' @ ' + time_str) if time_str else ''}\n"
            f"      {values_str}"
        )

    return "\n".join(lines)


def _build_index_section(items: list[dict[str, Any]]) -> str:
    """[INDEX SNAPSHOT] 섹션을 생성한다."""
    lines = ["[INDEX SNAPSHOT]"]

    for item in items:
        meta = item.get("metadata", {})
        symbol = meta.get("symbol", "?")
        name = meta.get("name", "")
        latest = meta.get("latest_close", 0)
        change_7d = meta.get("change_7d_pct", 0)

        lines.append(
            f"  {symbol} ({name}): {latest:,.2f} "
            f"({change_7d:+.2f}% over 7 days)"
        )

    return "\n".join(lines)


def _build_news_section(
    news: list[dict[str, Any]],
    screener: list[dict[str, Any]],
) -> str:
    """[NEWS SUMMARY] 섹션을 생성한다."""
    lines = ["[NEWS SUMMARY]"]

    if news:
        lines.append("Recent Headlines:")
        for item in news[:5]:
            headline = item.get("headline", "")
            if headline.startswith("["):
                # 태그 부분 제거하고 원본 제목만 사용
                headline = headline.split("] ", 1)[-1] if "] " in headline else headline
            meta = item.get("metadata", {})
            ticker = meta.get("ticker", "")
            lines.append(
                f"  - {headline[:100]}"
                f"{(' [' + ticker + ']') if ticker else ''}"
            )

    if screener:
        lines.append("Key Stock Screener Data:")
        # 변동률 기준 정렬
        for item in screener[:6]:
            meta = item.get("metadata", {})
            ticker = meta.get("ticker", "?")
            etf = meta.get("etf", "?")
            price = meta.get("price", "N/A")
            change = meta.get("change", "N/A")
            lines.append(
                f"  - {ticker} ({etf}): ${price} ({change})"
            )

    return "\n".join(lines)
