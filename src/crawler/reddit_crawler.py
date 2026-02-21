"""
Reddit crawler for r/wallstreetbets and r/investing.

Uses aiohttp to call Reddit's public JSON API (no OAuth required for read-only).
Falls back gracefully if Reddit rate-limits or blocks requests.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Reddit JSON endpoint (public, no auth required, rate-limited)
_REDDIT_BASE = "https://www.reddit.com"
_REDDIT_OAUTH_BASE = "https://oauth.reddit.com"


class RedditCrawler(BaseCrawler):
    """Crawls Reddit subreddits via the public JSON API.

    Collects hot and new posts from the configured subreddit.
    If REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars are set,
    uses OAuth for higher rate limits; otherwise uses public JSON API.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self.subreddit: str = source_config["subreddit"]
        self._client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self._client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._access_token: str | None = None
        self._token_expires: datetime | None = None

    async def _authenticate(self) -> str | None:
        """Obtain OAuth2 access token if credentials are available."""
        if not self._client_id or not self._client_secret:
            return None

        # Check if existing token is still valid
        if (
            self._access_token
            and self._token_expires
            and datetime.now(tz=timezone.utc) < self._token_expires
        ):
            return self._access_token

        session = await self.get_session()
        try:
            import aiohttp
            auth = aiohttp.BasicAuth(self._client_id, self._client_secret)
            async with session.post(
                "https://www.reddit.com/api/v1/access_token",
                data={
                    "grant_type": "client_credentials",
                },
                auth=auth,
                headers={"User-Agent": "TradingBot/2.0"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    from datetime import timedelta
                    self._token_expires = datetime.now(tz=timezone.utc) + timedelta(
                        seconds=expires_in - 60
                    )
                    logger.info("[%s] OAuth authenticated", self.name)
                    return self._access_token
                else:
                    logger.warning(
                        "[%s] OAuth failed: HTTP %d", self.name, resp.status
                    )
                    return None
        except Exception as e:
            logger.warning("[%s] OAuth error: %s", self.name, e)
            return None

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch hot and new posts from the subreddit."""
        token = await self._authenticate()
        articles: list[dict[str, Any]] = []

        for listing in ("hot", "new"):
            posts = await self._fetch_listing(listing, token)
            for post in posts:
                article = self._parse_post(post)
                if article is None:
                    continue
                if since and article["published_at"] < since:
                    continue
                articles.append(article)

        # Deduplicate by URL within this batch
        seen_urls: set[str] = set()
        unique: list[dict[str, Any]] = []
        for a in articles:
            if a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                unique.append(a)

        return unique

    async def _fetch_listing(
        self, listing: str, token: str | None
    ) -> list[dict[str, Any]]:
        """Fetch a single listing (hot/new) from Reddit."""
        session = await self.get_session()

        if token:
            base = _REDDIT_OAUTH_BASE
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "TradingBot/2.0",
            }
        else:
            base = _REDDIT_BASE
            headers = {"User-Agent": "TradingBot/2.0"}

        url = f"{base}/r/{self.subreddit}/{listing}.json?limit=25"

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] HTTP %d for r/%s/%s",
                        self.name, resp.status, self.subreddit, listing,
                    )
                    return []
                data = await resp.json()
                children = data.get("data", {}).get("children", [])
                return [child.get("data", {}) for child in children]
        except Exception as e:
            logger.error("[%s] Fetch error for %s: %s", self.name, listing, e)
            return []

    def _parse_post(self, post: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a Reddit post into a standardized article dict."""
        title = post.get("title", "").strip()
        if not title:
            return None

        # Skip stickied mod posts
        if post.get("stickied", False):
            return None

        selftext = post.get("selftext", "") or ""
        # Truncate long self-texts
        if len(selftext) > 3000:
            selftext = selftext[:3000] + "..."

        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else ""

        created_utc = post.get("created_utc", 0)
        published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)

        return {
            "headline": title,
            "content": selftext,
            "url": url,
            "published_at": published_at,
            "source": self.source_key,
            "language": self.language,
            "metadata": {
                "score": score,
                "num_comments": num_comments,
                "subreddit": self.subreddit,
            },
        }
