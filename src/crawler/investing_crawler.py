"""
Investing.com 경제 캘린더 및 지수 데이터 크롤러.

investiny 라이브러리와 BeautifulSoup를 사용하여 고영향 경제 이벤트와
주요 지수(SOX, NDX, SPX) 데이터를 수집한다.
요청 간 2초 딜레이로 레이트 리밋을 준수한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 추적 대상 지수
TRACKING_INDICES: dict[str, dict[str, Any]] = {
    "SOX": {
        "name": "Philadelphia Semiconductor Index",
        "investing_id": 21869,  # investiny에서 사용하는 ID
    },
    "NDX": {
        "name": "NASDAQ 100",
        "investing_id": 20,
    },
    "SPX": {
        "name": "S&P 500",
        "investing_id": 166,
    },
}

# 고영향 경제 이벤트 키워드 (importance >= 2 stars)
HIGH_IMPACT_KEYWORDS: set[str] = {
    "CPI",
    "Consumer Price Index",
    "PPI",
    "Producer Price Index",
    "Non-Farm Payrolls",
    "NFP",
    "Unemployment Rate",
    "FOMC",
    "Federal Funds Rate",
    "Interest Rate Decision",
    "GDP",
    "Gross Domestic Product",
    "Retail Sales",
    "PCE",
    "Core PCE",
    "ISM Manufacturing",
    "ISM Services",
    "Initial Jobless Claims",
    "ADP Employment",
    "Consumer Confidence",
    "Durable Goods",
    "Michigan Consumer Sentiment",
}

# 요청 간 딜레이 (초)
_REQUEST_DELAY = 2.0

# 지수 데이터 수집 기간 (일)
_HISTORY_DAYS = 7


class InvestingCrawler(BaseCrawler):
    """Investing.com의 경제 캘린더와 주요 지수 데이터를 수집하는 크롤러.

    investiny 라이브러리를 사용하여 히스토리컬 데이터를 가져오고,
    경제 캘린더는 BeautifulSoup 스크래핑으로 수집한다.
    레이트 리밋 준수를 위해 요청 간 2초 딜레이를 적용한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """경제 캘린더와 지수 데이터를 수집하여 기사 형태로 반환한다."""
        articles: list[dict[str, Any]] = []

        # 경제 캘린더 수집
        try:
            calendar_articles = await self.fetch_economic_calendar()
            articles.extend(calendar_articles)
        except Exception as e:
            logger.error(
                "[%s] 경제 캘린더 수집 실패: %s", self.name, e, exc_info=True
            )

        await asyncio.sleep(_REQUEST_DELAY)

        # 지수 데이터 수집
        try:
            index_articles = await self.fetch_index_data()
            articles.extend(index_articles)
        except Exception as e:
            logger.error(
                "[%s] 지수 데이터 수집 실패: %s", self.name, e, exc_info=True
            )

        return articles

    async def fetch_economic_calendar(self) -> list[dict[str, Any]]:
        """고영향 경제 이벤트를 수집한다.

        Investing.com 경제 캘린더에서 importance >= 2 (별 2개 이상)인
        이벤트만 필터링하여 반환한다.

        Returns:
            경제 이벤트 기사 목록.
        """
        session = await self.get_session()
        articles: list[dict[str, Any]] = []

        # Investing.com 경제 캘린더 API (비공식)
        url = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"

        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (
            datetime.now(tz=timezone.utc) + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*",
            "Referer": "https://www.investing.com/economic-calendar/",
        }

        # POST 데이터
        form_data = {
            "dateFrom": today,
            "dateTo": tomorrow,
            "country[]": "5",  # US
            "importance[]": ["2", "3"],  # 2성, 3성 이벤트만
            "limit_from": "0",
        }

        try:
            async with session.post(
                url, headers=headers, data=form_data
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] 캘린더 API HTTP %d, 스크래핑 폴백",
                        self.name, resp.status,
                    )
                    return await self._scrape_calendar_fallback()

                response_data = await resp.json()
                html = response_data.get("data", "")

        except Exception as e:
            logger.info(
                "[%s] 캘린더 API 실패, 스크래핑 폴백: %s", self.name, e
            )
            return await self._scrape_calendar_fallback()

        if html:
            articles = self._parse_calendar_html(html)

        logger.info(
            "[%s] 경제 캘린더 이벤트 %d건 수집", self.name, len(articles)
        )
        return articles

    async def _scrape_calendar_fallback(self) -> list[dict[str, Any]]:
        """경제 캘린더 API 실패 시 직접 스크래핑으로 대체한다."""
        session = await self.get_session()

        url = "https://www.investing.com/economic-calendar/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html",
        }

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] 캘린더 스크래핑 HTTP %d",
                        self.name, resp.status,
                    )
                    return []
                html = await resp.text()
        except Exception as e:
            logger.warning(
                "[%s] 캘린더 스크래핑 실패: %s", self.name, e
            )
            return []

        return self._parse_calendar_html(html)

    def _parse_calendar_html(self, html: str) -> list[dict[str, Any]]:
        """경제 캘린더 HTML을 파싱하여 고영향 이벤트만 추출한다."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("[%s] beautifulsoup4 패키지 미설치", self.name)
            return []

        soup = BeautifulSoup(html, "html.parser")
        articles: list[dict[str, Any]] = []

        # 이벤트 행 파싱
        rows = soup.select("tr[id^='eventRowId']")
        if not rows:
            rows = soup.select("tr.js-event-item")
        if not rows:
            rows = soup.select("tr[data-event-datetime]")

        for row in rows:
            try:
                event = self._parse_event_row(row)
                if event:
                    articles.append(event)
            except Exception as e:
                logger.debug("[%s] 이벤트 행 파싱 오류: %s", self.name, e)
                continue

        return articles

    def _parse_event_row(self, row: Any) -> dict[str, Any] | None:
        """단일 경제 이벤트 행을 파싱한다."""
        # 이벤트명 추출
        event_cell = row.select_one(
            "td.event a, td.left.event a, .event a"
        )
        if not event_cell:
            return None

        event_name = event_cell.get_text(strip=True)
        if not event_name:
            return None

        # importance (별 개수) 추출
        importance = 0
        bull_icons = row.select("td.sentiment i.grayFullBullishIcon")
        if bull_icons:
            importance = len(bull_icons)
        else:
            # 대안: data-img_key 속성
            for i in range(3, 0, -1):
                if row.select_one(f"td[data-img_key='bull{i}']"):
                    importance = i
                    break

        # importance 2 미만은 무시
        if importance < 2:
            # 키워드로도 체크
            is_high_impact = any(
                kw.lower() in event_name.lower()
                for kw in HIGH_IMPACT_KEYWORDS
            )
            if not is_high_impact:
                return None

        # 시간 추출
        time_cell = row.select_one("td.time, td.first.left")
        time_text = time_cell.get_text(strip=True) if time_cell else ""

        # 실제/예상/이전 값 추출
        actual_cell = row.select_one("td.act, td.bold")
        forecast_cell = row.select_one("td.fore")
        previous_cell = row.select_one("td.prev")

        actual = actual_cell.get_text(strip=True) if actual_cell else ""
        forecast = forecast_cell.get_text(strip=True) if forecast_cell else ""
        previous = previous_cell.get_text(strip=True) if previous_cell else ""

        # 국가 추출
        country_cell = row.select_one("td.flagCur")
        country = country_cell.get_text(strip=True) if country_cell else "US"

        headline = (
            f"[Investing Calendar] {country} {event_name} "
            f"({'*' * importance})"
        )

        content_parts = []
        if actual:
            content_parts.append(f"Actual: {actual}")
        if forecast:
            content_parts.append(f"Forecast: {forecast}")
        if previous:
            content_parts.append(f"Previous: {previous}")
        content = " | ".join(content_parts) if content_parts else event_name

        event_url = event_cell.get("href", "")
        if event_url and not event_url.startswith("http"):
            event_url = f"https://www.investing.com{event_url}"

        return {
            "headline": headline,
            "content": content,
            "url": event_url,
            "published_at": datetime.now(tz=timezone.utc),
            "source": self.source_key,
            "language": "en",
            "metadata": {
                "data_type": "economic_calendar",
                "event_name": event_name,
                "importance": importance,
                "country": country,
                "time": time_text,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
            },
        }

    async def fetch_index_data(self) -> list[dict[str, Any]]:
        """SOX, NDX, SPX 지수의 7일 히스토리컬 데이터를 수집한다.

        investiny 라이브러리를 사용하여 히스토리컬 가격 데이터를 가져온다.
        라이브러리가 없을 경우 aiohttp로 직접 조회한다.

        Returns:
            지수별 히스토리컬 데이터를 담은 기사 목록.
        """
        articles: list[dict[str, Any]] = []

        for symbol, info in TRACKING_INDICES.items():
            await asyncio.sleep(_REQUEST_DELAY)

            try:
                hist_data = await self._fetch_index_history(
                    info["investing_id"], symbol
                )
                if not hist_data:
                    continue

                # 최신 가격 및 변동률 계산
                latest = hist_data[-1] if hist_data else {}
                oldest = hist_data[0] if hist_data else {}

                latest_close = latest.get("close", 0)
                oldest_close = oldest.get("close", 0)
                change_pct = (
                    ((latest_close - oldest_close) / oldest_close * 100)
                    if oldest_close
                    else 0
                )

                headline = (
                    f"[Index] {symbol} ({info['name']}): "
                    f"{latest_close:,.2f} ({change_pct:+.2f}% 7d)"
                )

                # 히스토리컬 데이터를 텍스트로 변환
                hist_text_parts = []
                for point in hist_data:
                    hist_text_parts.append(
                        f"{point.get('date', 'N/A')}: "
                        f"O={point.get('open', 0):,.2f} "
                        f"H={point.get('high', 0):,.2f} "
                        f"L={point.get('low', 0):,.2f} "
                        f"C={point.get('close', 0):,.2f}"
                    )
                content = (
                    f"{symbol} 7-Day History:\n"
                    + "\n".join(hist_text_parts)
                )

                articles.append({
                    "headline": headline,
                    "content": content,
                    "url": f"https://www.investing.com/indices/{symbol.lower()}",
                    "published_at": datetime.now(tz=timezone.utc),
                    "source": self.source_key,
                    "language": "en",
                    "metadata": {
                        "data_type": "index_historical",
                        "symbol": symbol,
                        "name": info["name"],
                        "latest_close": latest_close,
                        "change_7d_pct": round(change_pct, 2),
                        "history": hist_data,
                    },
                })

            except Exception as e:
                logger.warning(
                    "[%s] 지수 %s 데이터 수집 실패: %s",
                    self.name, symbol, e,
                )
                continue

        logger.info("[%s] 지수 데이터 %d건 수집", self.name, len(articles))
        return articles

    async def _fetch_index_history(
        self, investing_id: int, symbol: str
    ) -> list[dict[str, Any]]:
        """investiny를 사용하여 지수 히스토리컬 데이터를 조회한다."""
        try:
            from investiny import historical_data

            end_date = datetime.now(tz=timezone.utc)
            start_date = end_date - timedelta(days=_HISTORY_DAYS)

            data = await asyncio.to_thread(
                historical_data,
                investing_id=investing_id,
                from_date=start_date.strftime("%m/%d/%Y"),
                to_date=end_date.strftime("%m/%d/%Y"),
            )

            if not data or "date" not in data:
                return []

            history: list[dict[str, Any]] = []
            dates = data.get("date", [])
            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])

            for i in range(len(dates)):
                history.append({
                    "date": dates[i] if i < len(dates) else "",
                    "open": float(opens[i]) if i < len(opens) else 0,
                    "high": float(highs[i]) if i < len(highs) else 0,
                    "low": float(lows[i]) if i < len(lows) else 0,
                    "close": float(closes[i]) if i < len(closes) else 0,
                })

            return history

        except ImportError:
            logger.info(
                "[%s] investiny 미설치, aiohttp 폴백 (%s)",
                self.name, symbol,
            )
            return await self._fetch_index_history_fallback(symbol)

        except Exception as e:
            logger.warning(
                "[%s] investiny 조회 실패 (%s): %s",
                self.name, symbol, e,
            )
            return await self._fetch_index_history_fallback(symbol)

    async def _fetch_index_history_fallback(
        self, symbol: str
    ) -> list[dict[str, Any]]:
        """investiny 실패 시 Yahoo Finance API로 대체 조회한다."""
        session = await self.get_session()

        # Yahoo Finance 심볼 매핑
        yahoo_symbols = {
            "SOX": "%5ESOX",
            "NDX": "%5ENDX",
            "SPX": "%5EGSPC",
        }
        yahoo_symbol = yahoo_symbols.get(symbol)
        if not yahoo_symbol:
            return []

        end_ts = int(datetime.now(tz=timezone.utc).timestamp())
        start_ts = end_ts - (_HISTORY_DAYS * 86400)

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{yahoo_symbol}?period1={start_ts}&period2={end_ts}"
            f"&interval=1d"
        )

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

            result = data.get("chart", {}).get("result", [])
            if not result:
                return []

            timestamps = result[0].get("timestamp", [])
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]

            history: list[dict[str, Any]] = []
            for i, ts in enumerate(timestamps):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                history.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "open": float(quote.get("open", [0])[i] or 0),
                    "high": float(quote.get("high", [0])[i] or 0),
                    "low": float(quote.get("low", [0])[i] or 0),
                    "close": float(quote.get("close", [0])[i] or 0),
                })

            return history

        except Exception as e:
            logger.warning(
                "[%s] Yahoo Finance 폴백 실패 (%s): %s",
                self.name, symbol, e,
            )
            return []
