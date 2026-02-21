"""
DART (Korean Financial Supervisory Service) crawler.

Uses the OpenDART API to fetch recent corporate filings.
Requires DART_API_KEY environment variable. Skips gracefully if not set.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

_DART_API_BASE = "https://opendart.fss.or.kr/api"


class DARTCrawler(BaseCrawler):
    """Crawls DART (Data Analysis, Retrieval and Transfer System) for Korean filings.

    Monitors disclosure filings from Korean companies. Particularly useful
    for Korean companies with US exposure or dual-listed stocks.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self._api_key = os.getenv("DART_API_KEY", "")

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch recent DART filings."""
        if not self._api_key:
            logger.info("[%s] DART_API_KEY not set, skipping", self.name)
            return []

        if since is None:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        # Convert since to Korean date format (YYYYMMDD)
        # DART uses KST (UTC+9)
        since_kst = since + timedelta(hours=9)
        begin_date = since_kst.strftime("%Y%m%d")
        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=9)).strftime(
            "%Y%m%d"
        )

        articles: list[dict[str, Any]] = []
        page = 1
        max_pages = 3  # Limit pages to avoid excessive API calls

        while page <= max_pages:
            filings = await self._fetch_page(begin_date, end_date, page)
            if not filings:
                break
            articles.extend(filings)
            page += 1

        return articles

    async def _fetch_page(
        self, begin_date: str, end_date: str, page: int
    ) -> list[dict[str, Any]]:
        """Fetch a single page of DART filings."""
        session = await self.get_session()

        params = {
            "crtfc_key": self._api_key,
            "bgn_de": begin_date,
            "end_de": end_date,
            "page_no": str(page),
            "page_count": "100",
        }

        url = f"{_DART_API_BASE}/list.json"

        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] HTTP %d from DART API", self.name, resp.status
                    )
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("[%s] DART API error: %s", self.name, e)
            return []

        status = data.get("status", "")
        if status == "013":
            # No data found
            return []
        if status != "000":
            logger.warning(
                "[%s] DART API status %s: %s",
                self.name, status, data.get("message", ""),
            )
            return []

        filings = data.get("list", [])
        articles: list[dict[str, Any]] = []

        for filing in filings:
            article = self._parse_filing(filing)
            if article:
                articles.append(article)

        return articles

    def _parse_filing(self, filing: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a DART filing into a standardized article dict."""
        report_nm = filing.get("report_nm", "").strip()
        corp_name = filing.get("corp_name", "").strip()

        if not report_nm or not corp_name:
            return None

        headline = f"[{corp_name}] {report_nm}"

        # Parse filing date (YYYYMMDD format in KST)
        rcept_dt = filing.get("rcept_dt", "")
        published_at = self._parse_dart_date(rcept_dt)

        # Build DART viewer URL
        rcept_no = filing.get("rcept_no", "")
        url = ""
        if rcept_no:
            url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

        flr_nm = filing.get("flr_nm", "")  # Filer name
        corp_code = filing.get("corp_code", "")
        stock_code = filing.get("stock_code", "")

        return {
            "headline": headline,
            "content": f"Filing: {report_nm} by {corp_name} ({flr_nm})",
            "url": url,
            "published_at": published_at,
            "source": self.source_key,
            "language": self.language,
            "metadata": {
                "corp_name": corp_name,
                "corp_code": corp_code,
                "stock_code": stock_code,
                "report_name": report_nm,
                "filer_name": flr_nm,
            },
        }

    @staticmethod
    def _parse_dart_date(date_str: str) -> datetime:
        """Parse DART date string (YYYYMMDD) to datetime (UTC)."""
        if len(date_str) == 8:
            try:
                # DART dates are in KST (UTC+9)
                kst_dt = datetime.strptime(date_str, "%Y%m%d").replace(
                    hour=9, minute=0
                )
                # Convert to UTC
                utc_dt = kst_dt - timedelta(hours=9)
                return utc_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(tz=timezone.utc)
