"""
SEC EDGAR filing crawler.

Uses the EDGAR full-text search API (efts.sec.gov) to find recent 8-K,
10-K, and 10-Q filings. No API key is required but a valid User-Agent
header with contact information is mandatory per SEC policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# SEC EDGAR full-text search endpoint
_EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
# SEC EDGAR RSS feed for recent filings
_EDGAR_RSS = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&dateb=&owner=include&count={count}&search_text=&start=0&output=atom"
# SEC EDGAR company search API
_EDGAR_COMPANY_API = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt={start}&enddt={end}&forms={forms}"
# EDGAR full-text search (preferred)
_EDGAR_FULLTEXT = "https://efts.sec.gov/LATEST/search-index"


class SECEdgarCrawler(BaseCrawler):
    """Crawls SEC EDGAR for recent 8-K, 10-K, 10-Q filings.

    Uses the EDGAR ATOM feed for recent filings which does not require
    authentication, only a compliant User-Agent header.
    """

    # Form types to monitor
    FORM_TYPES = ("8-K", "10-K", "10-Q", "6-K")

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch recent SEC filings from EDGAR ATOM feeds."""
        if since is None:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        articles: list[dict[str, Any]] = []

        for form_type in self.FORM_TYPES:
            filings = await self._fetch_filings(form_type, since)
            articles.extend(filings)

        return articles

    async def _fetch_filings(
        self, form_type: str, since: datetime
    ) -> list[dict[str, Any]]:
        """Fetch filings for a specific form type via EDGAR ATOM feed."""
        session = await self.get_session()

        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar"
            f"?action=getcurrent&type={form_type}&dateb=&owner=include"
            f"&count=40&search_text=&start=0&output=atom"
        )

        headers = {
            "User-Agent": "TradingBot admin@localhost",
            "Accept": "application/atom+xml, application/xml, text/xml",
        }

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] HTTP %d for %s feed",
                        self.name, resp.status, form_type,
                    )
                    return []
                raw = await resp.text()
        except Exception as e:
            logger.error("[%s] Fetch error for %s: %s", self.name, form_type, e)
            return []

        return self._parse_atom_feed(raw, form_type, since)

    def _parse_atom_feed(
        self, raw: str, form_type: str, since: datetime
    ) -> list[dict[str, Any]]:
        """Parse EDGAR ATOM feed XML into article dicts."""
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

            # Extract company name and CIK from title if possible
            # Typical format: "8-K - COMPANY NAME (0001234567) (Filer)"
            company_name = self._extract_company_name(title)

            articles.append({
                "headline": f"[{form_type}] {title}",
                "content": summary[:3000],
                "url": link,
                "published_at": published_at,
                "source": self.source_key,
                "language": self.language,
                "metadata": {
                    "form_type": form_type,
                    "company_name": company_name,
                },
            })

        return articles

    def _parse_entry_date(self, entry: Any) -> datetime:
        """Parse publication date from an ATOM entry."""
        for field in ("updated_parsed", "published_parsed"):
            parsed = getattr(entry, field, None)
            if parsed:
                try:
                    from calendar import timegm
                    ts = timegm(parsed)
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except (ValueError, OverflowError):
                    pass

        for raw_field in ("updated", "published"):
            raw = getattr(entry, raw_field, None)
            if raw:
                try:
                    from email.utils import parsedate_to_datetime
                    return parsedate_to_datetime(raw).astimezone(timezone.utc)
                except (ValueError, TypeError):
                    pass

        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _extract_company_name(title: str) -> str:
        """Extract company name from EDGAR filing title.

        Typical format: '8-K - APPLE INC (0000320193) (Filer)'
        """
        parts = title.split(" - ", 1)
        if len(parts) < 2:
            return title

        rest = parts[1]
        # Remove CIK number and (Filer) suffix
        import re
        match = re.match(r"(.+?)\s*\(\d+\)", rest)
        if match:
            return match.group(1).strip()
        return rest.strip()
