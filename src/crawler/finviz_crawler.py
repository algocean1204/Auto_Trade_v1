"""
Finviz 데이터 크롤러.

finvizfinance 패키지를 사용하여 ETF 기초 종목의 스크리너, 뉴스, 내부자 거래
데이터를 수집한다. 2X 레버리지 ETF(SOXL, QLD, SSO)의 주요 구성 종목을 추적한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ETF -> 기초 주요 종목 매핑
ETF_BASE_TICKERS: dict[str, list[str]] = {
    "SOXL": ["NVDA", "AMD", "AVGO", "TSM", "INTC", "MU"],
    "QLD": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA"],
    "SSO": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B"],
}

# 내부자 거래 추적 대상 티커
INSIDER_TICKERS: list[str] = ["NVDA", "AMD", "AAPL", "MSFT", "GOOGL", "META"]

# 모든 ETF 기초 종목의 합집합 (중복 제거)
ALL_BASE_TICKERS: list[str] = sorted(
    set(t for tickers in ETF_BASE_TICKERS.values() for t in tickers)
)


class FinvizCrawler(BaseCrawler):
    """Finviz 스크리너, 뉴스, 내부자 거래 데이터를 수집하는 크롤러.

    finvizfinance 라이브러리를 사용하며, 동기 라이브러리이므로
    asyncio.to_thread로 감싸서 비동기로 실행한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """스크리너, 뉴스, 내부자 거래 데이터를 병렬로 수집한다."""
        results: list[dict[str, Any]] = []

        screener_task = self.fetch_screener_data()
        news_task = self.fetch_news(since)
        insider_task = self.fetch_insider_trades()

        screener_result, news_result, insider_result = await asyncio.gather(
            screener_task, news_task, insider_task,
            return_exceptions=True,
        )

        if isinstance(screener_result, Exception):
            logger.error("[%s] 스크리너 수집 실패: %s", self.name, screener_result)
        else:
            results.extend(screener_result)

        if isinstance(news_result, Exception):
            logger.error("[%s] 뉴스 수집 실패: %s", self.name, news_result)
        else:
            results.extend(news_result)

        if isinstance(insider_result, Exception):
            logger.error("[%s] 내부자 거래 수집 실패: %s", self.name, insider_result)
        else:
            results.extend(insider_result)

        return results

    async def fetch_screener_data(self) -> list[dict[str, Any]]:
        """ETF 기초 종목의 스크리너 데이터를 수집한다.

        주요 재무 지표(시가총액, P/E, 변동률 등)를 조회하여
        AI 판단 컨텍스트에 활용한다.
        """
        try:
            from finvizfinance.quote import finvizfinance

            articles: list[dict[str, Any]] = []

            for etf, tickers in ETF_BASE_TICKERS.items():
                for ticker in tickers:
                    try:
                        stock = await asyncio.to_thread(finvizfinance, ticker)
                        fundament = await asyncio.to_thread(stock.ticker_fundament)

                        price = fundament.get("Price", "N/A")
                        change = fundament.get("Change", "N/A")
                        market_cap = fundament.get("Market Cap", "N/A")
                        pe = fundament.get("P/E", "N/A")
                        volume = fundament.get("Volume", "N/A")

                        headline = (
                            f"[Finviz Screener] {ticker} ({etf} base): "
                            f"Price={price}, Change={change}"
                        )
                        content = (
                            f"Ticker: {ticker} | ETF: {etf} | "
                            f"Price: {price} | Change: {change} | "
                            f"Market Cap: {market_cap} | P/E: {pe} | "
                            f"Volume: {volume}"
                        )

                        articles.append({
                            "headline": headline,
                            "content": content,
                            "url": f"https://finviz.com/quote.ashx?t={ticker}",
                            "published_at": datetime.now(tz=timezone.utc),
                            "source": self.source_key,
                            "language": "en",
                            "metadata": {
                                "data_type": "screener",
                                "ticker": ticker,
                                "etf": etf,
                                "price": price,
                                "change": change,
                                "market_cap": market_cap,
                                "pe": pe,
                                "volume": volume,
                            },
                        })
                    except Exception as e:
                        logger.warning(
                            "[%s] 스크리너 수집 실패 (%s): %s",
                            self.name, ticker, e,
                        )
                        continue

            logger.info("[%s] 스크리너 데이터 %d건 수집", self.name, len(articles))
            return articles

        except ImportError:
            logger.error("[%s] finvizfinance 패키지 미설치", self.name)
            return []
        except Exception as e:
            logger.error("[%s] 스크리너 수집 오류: %s", self.name, e, exc_info=True)
            return []

    async def fetch_news(
        self, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """ETF 기초 종목 관련 뉴스를 수집한다.

        ETF별 상위 3개 뉴스를 가져오며, URL 기준으로 중복을 제거한다.
        """
        try:
            from finvizfinance.quote import finvizfinance

            articles: list[dict[str, Any]] = []
            seen_urls: set[str] = set()

            for etf, tickers in ETF_BASE_TICKERS.items():
                etf_news_count = 0
                for ticker in tickers:
                    if etf_news_count >= 3:
                        break
                    try:
                        stock = await asyncio.to_thread(finvizfinance, ticker)
                        news_df = await asyncio.to_thread(stock.ticker_news)

                        if news_df is None or news_df.empty:
                            continue

                        for _, row in news_df.iterrows():
                            if etf_news_count >= 3:
                                break

                            url = str(row.get("Link", ""))
                            if url in seen_urls or not url:
                                continue
                            seen_urls.add(url)

                            title = str(row.get("Title", ""))
                            date_str = row.get("Date", None)

                            published_at = datetime.now(tz=timezone.utc)
                            if date_str is not None:
                                try:
                                    import pandas as pd
                                    if isinstance(date_str, pd.Timestamp):
                                        published_at = date_str.to_pydatetime()
                                        if published_at.tzinfo is None:
                                            published_at = published_at.replace(
                                                tzinfo=timezone.utc
                                            )
                                except Exception as exc:
                                    logger.debug("Finviz 날짜 파싱 실패: %s", exc)

                            if since and published_at < since:
                                continue

                            source_name = str(row.get("Source", "Finviz"))

                            articles.append({
                                "headline": f"[Finviz News] {title}",
                                "content": f"{title} (via {source_name})",
                                "url": url,
                                "published_at": published_at,
                                "source": self.source_key,
                                "language": "en",
                                "metadata": {
                                    "data_type": "news",
                                    "ticker": ticker,
                                    "etf": etf,
                                    "news_source": source_name,
                                },
                            })
                            etf_news_count += 1

                    except Exception as e:
                        logger.warning(
                            "[%s] 뉴스 수집 실패 (%s): %s",
                            self.name, ticker, e,
                        )
                        continue

            logger.info("[%s] 뉴스 %d건 수집 (중복 제거 완료)", self.name, len(articles))
            return articles

        except ImportError:
            logger.error("[%s] finvizfinance 패키지 미설치", self.name)
            return []
        except Exception as e:
            logger.error("[%s] 뉴스 수집 오류: %s", self.name, e, exc_info=True)
            return []

    async def fetch_insider_trades(self) -> list[dict[str, Any]]:
        """주요 티커의 내부자 거래 데이터를 수집한다.

        NVDA, AMD, AAPL, MSFT, GOOGL, META의 최근 내부자 매매를
        조회하여 대규모 매도 등 이상 신호를 감지한다.
        """
        try:
            from finvizfinance.quote import finvizfinance

            articles: list[dict[str, Any]] = []

            for ticker in INSIDER_TICKERS:
                try:
                    stock = await asyncio.to_thread(finvizfinance, ticker)
                    insider_df = await asyncio.to_thread(stock.ticker_inside_trader)

                    if insider_df is None or insider_df.empty:
                        continue

                    # 최근 5건만 수집
                    for _, row in insider_df.head(5).iterrows():
                        owner = str(row.get("Insider Trading", ""))
                        relationship = str(row.get("Relationship", ""))
                        transaction = str(row.get("Transaction", ""))
                        value = str(row.get("Value ($)", ""))
                        shares = str(row.get("#Shares Total", ""))
                        date_str = row.get("Date", "")

                        headline = (
                            f"[Insider] {ticker}: {owner} {transaction}"
                        )
                        content = (
                            f"Ticker: {ticker} | Insider: {owner} | "
                            f"Relationship: {relationship} | "
                            f"Transaction: {transaction} | "
                            f"Value: ${value} | Shares: {shares}"
                        )

                        articles.append({
                            "headline": headline,
                            "content": content,
                            "url": f"https://finviz.com/quote.ashx?t={ticker}",
                            "published_at": datetime.now(tz=timezone.utc),
                            "source": self.source_key,
                            "language": "en",
                            "metadata": {
                                "data_type": "insider_trade",
                                "ticker": ticker,
                                "insider_name": owner,
                                "relationship": relationship,
                                "transaction_type": transaction,
                                "value": value,
                                "shares": shares,
                                "trade_date": str(date_str),
                            },
                        })

                except Exception as e:
                    logger.warning(
                        "[%s] 내부자 거래 수집 실패 (%s): %s",
                        self.name, ticker, e,
                    )
                    continue

            logger.info(
                "[%s] 내부자 거래 %d건 수집", self.name, len(articles)
            )
            return articles

        except ImportError:
            logger.error("[%s] finvizfinance 패키지 미설치", self.name)
            return []
        except Exception as e:
            logger.error(
                "[%s] 내부자 거래 수집 오류: %s", self.name, e, exc_info=True
            )
            return []
