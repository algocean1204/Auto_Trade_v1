"""
Economic calendar crawler.

Scrapes economic event data (CPI, PPI, employment, FOMC, etc.) from
a public economic calendar source. Uses BeautifulSoup for HTML parsing.

Falls back to the Federal Reserve Economic Data (FRED) calendar RSS
if scraping fails.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# High-impact economic events to monitor
_HIGH_IMPACT_EVENTS = {
    "CPI",
    "Consumer Price Index",
    "PPI",
    "Producer Price Index",
    "Non-Farm Payrolls",
    "NFP",
    "Nonfarm Payrolls",
    "Unemployment Rate",
    "FOMC",
    "Federal Funds Rate",
    "Interest Rate Decision",
    "GDP",
    "Gross Domestic Product",
    "Retail Sales",
    "PCE",
    "Personal Consumption Expenditures",
    "Core PCE",
    "ISM Manufacturing",
    "ISM Services",
    "Initial Jobless Claims",
    "ADP Employment",
    "Consumer Confidence",
    "Durable Goods",
    "Trade Balance",
    "Industrial Production",
    "Housing Starts",
    "Building Permits",
    "Michigan Consumer Sentiment",
    "ECB Interest Rate",
    "BOJ Interest Rate",
    "BOE Interest Rate",
}

# FRED economic calendar RSS
_FRED_CALENDAR_URL = "https://research.stlouisfed.org/useraccount/datalists/246734/rss"
# Alternative: Treasury yield data
_TREASURY_RSS = "https://home.treasury.gov/system/files/276/yield-curve-rates-all.xml"


class EconomicCalendarCrawler(BaseCrawler):
    """Crawls economic calendar events relevant to market-moving indicators.

    Primary strategy: scrape a publicly available economic calendar page.
    Fallback: use FRED RSS or Treasury data.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch upcoming and recent economic events."""
        if since is None:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        articles: list[dict[str, Any]] = []

        # Strategy 1: Try scraping Forex Factory or similar public calendar
        calendar_events = await self._scrape_calendar()
        if calendar_events:
            articles.extend(calendar_events)

        # Strategy 2: Fetch FRED calendar RSS as supplement
        fred_events = await self._fetch_fred_rss(since)
        articles.extend(fred_events)

        # Filter by since timestamp
        articles = [a for a in articles if a["published_at"] >= since]

        return articles

    async def _scrape_calendar(self) -> list[dict[str, Any]]:
        """Attempt to scrape economic calendar from a public source.

        Returns empty list if scraping fails (site may block bots).
        """
        session = await self.get_session()

        # Use a publicly accessible economic calendar
        url = "https://www.forexfactory.com/calendar?week=this"

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
                    logger.info(
                        "[%s] Calendar scrape HTTP %d, falling back",
                        self.name, resp.status,
                    )
                    return []
                html = await resp.text()
        except Exception as e:
            logger.info("[%s] Calendar scrape failed: %s", self.name, e)
            return []

        return self._parse_calendar_html(html)

    def _parse_calendar_html(self, html: str) -> list[dict[str, Any]]:
        """Parse economic calendar HTML into article dicts."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        articles: list[dict[str, Any]] = []

        # Look for calendar event rows
        rows = soup.select("tr.calendar__row")
        if not rows:
            # Try alternative selectors
            rows = soup.select("tr[data-eventid]")

        for row in rows:
            event = self._parse_calendar_row(row)
            if event:
                articles.append(event)

        logger.info("[%s] Parsed %d calendar events", self.name, len(articles))
        return articles

    def _parse_calendar_row(self, row: Any) -> dict[str, Any] | None:
        """Parse a single calendar row into an article dict."""
        from bs4 import Tag
        if not isinstance(row, Tag):
            return None

        # Extract event name
        event_cell = row.select_one(".calendar__event-title, td.event")
        if not event_cell:
            return None
        event_name = event_cell.get_text(strip=True)
        if not event_name:
            return None

        # Check if this is a high-impact event
        is_high_impact = any(
            kw.lower() in event_name.lower() for kw in _HIGH_IMPACT_EVENTS
        )

        # Extract impact level
        impact_cell = row.select_one(
            ".calendar__impact-icon--high, "
            ".calendar__impact-icon--medium, "
            ".calendar__impact-icon--low, "
            "td.impact"
        )
        impact = "unknown"
        if impact_cell:
            classes = impact_cell.get("class", [])
            if any("high" in c for c in classes):
                impact = "high"
            elif any("medium" in c for c in classes):
                impact = "medium"
            elif any("low" in c for c in classes):
                impact = "low"

        # Extract currency / country
        currency_cell = row.select_one(".calendar__currency, td.currency")
        currency = currency_cell.get_text(strip=True) if currency_cell else ""

        # Extract actual / forecast / previous values
        actual_cell = row.select_one(".calendar__actual, td.actual")
        forecast_cell = row.select_one(".calendar__forecast, td.forecast")
        previous_cell = row.select_one(".calendar__previous, td.previous")

        actual = actual_cell.get_text(strip=True) if actual_cell else ""
        forecast = forecast_cell.get_text(strip=True) if forecast_cell else ""
        previous = previous_cell.get_text(strip=True) if previous_cell else ""

        headline = f"[Economic] {currency} {event_name}"
        content_parts = []
        if actual:
            content_parts.append(f"Actual: {actual}")
        if forecast:
            content_parts.append(f"Forecast: {forecast}")
        if previous:
            content_parts.append(f"Previous: {previous}")
        content = " | ".join(content_parts) if content_parts else event_name

        return {
            "headline": headline,
            "content": content,
            "url": "",
            "published_at": datetime.now(tz=timezone.utc),
            "source": self.source_key,
            "language": self.language,
            "metadata": {
                "event_name": event_name,
                "impact": impact,
                "is_high_impact": is_high_impact,
                "currency": currency,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
            },
        }

    async def _fetch_fred_rss(self, since: datetime) -> list[dict[str, Any]]:
        """Fetch FRED economic data calendar via RSS."""
        session = await self.get_session()

        try:
            async with session.get(_FRED_CALENDAR_URL) as resp:
                if resp.status != 200:
                    return []
                raw = await resp.text()
        except Exception as e:
            logger.debug("[%s] FRED RSS fetch failed: %s", self.name, e)
            return []

        import feedparser
        feed = feedparser.parse(raw)
        articles: list[dict[str, Any]] = []

        for entry in feed.entries:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue

            # Parse date
            published_at = self._parse_entry_date(entry)
            if published_at < since:
                continue

            link = getattr(entry, "link", "")
            summary = getattr(entry, "summary", "") or ""

            is_high_impact = any(
                kw.lower() in title.lower() for kw in _HIGH_IMPACT_EVENTS
            )

            articles.append({
                "headline": f"[FRED] {title}",
                "content": summary[:2000],
                "url": link,
                "published_at": published_at,
                "source": self.source_key,
                "language": "en",
                "metadata": {
                    "event_name": title,
                    "is_high_impact": is_high_impact,
                    "data_source": "fred",
                },
            })

        return articles

    @staticmethod
    def _parse_entry_date(entry: Any) -> datetime:
        """Parse date from RSS entry."""
        for field in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, field, None)
            if parsed:
                try:
                    from calendar import timegm
                    ts = timegm(parsed)
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except (ValueError, OverflowError):
                    pass
        return datetime.now(tz=timezone.utc)
