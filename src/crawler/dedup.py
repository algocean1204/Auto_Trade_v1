"""
Redis-based deduplication checker.

Uses SHA-256 hash of article headlines to detect and skip duplicates.
Hashes are stored in a Redis SET with a configurable TTL (default 48 hours).
"""

from __future__ import annotations

import hashlib
from typing import Any

import redis.asyncio as aioredis

from src.db.connection import get_redis
from src.utils.logger import get_logger

logger = get_logger(__name__)

_DEDUP_KEY_PREFIX = "crawl:dedup:"
_DEFAULT_TTL_SECONDS = 48 * 3600  # 48 hours


class DedupChecker:
    """Redis-backed deduplication for crawled articles.

    Stores SHA-256 hashes of headlines in Redis with TTL expiration.
    Provides both single-check and batch-check methods.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        key_prefix: str = _DEDUP_KEY_PREFIX,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._key_prefix = key_prefix

    def _get_redis(self) -> aioredis.Redis:
        """Lazy-load Redis client."""
        if self._redis is None:
            self._redis = get_redis()
        return self._redis

    @staticmethod
    def compute_hash(headline: str) -> str:
        """Compute SHA-256 hash of a headline for dedup comparison.

        Normalizes by lowercasing and stripping whitespace before hashing.
        """
        normalized = headline.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _make_key(self, content_hash: str) -> str:
        """Build the Redis key for a content hash."""
        return f"{self._key_prefix}{content_hash}"

    async def is_duplicate(self, headline: str) -> bool:
        """Check if an article headline has been seen before.

        Returns True if duplicate, False if new.
        """
        r = self._get_redis()
        content_hash = self.compute_hash(headline)
        key = self._make_key(content_hash)

        try:
            exists = await r.exists(key)
            return bool(exists)
        except Exception as e:
            logger.error("Redis dedup check failed: %s", e)
            # On Redis failure, assume not duplicate to avoid data loss
            return False

    async def mark_seen(self, headline: str) -> str:
        """Mark a headline as seen and return its content hash.

        Sets the hash in Redis with TTL expiration.
        """
        r = self._get_redis()
        content_hash = self.compute_hash(headline)
        key = self._make_key(content_hash)

        try:
            await r.setex(key, self._ttl, "1")
        except Exception as e:
            logger.error("Redis dedup mark failed: %s", e)

        return content_hash

    async def check_and_mark(self, headline: str) -> tuple[bool, str]:
        """Check if duplicate and mark as seen in one operation.

        Returns:
            Tuple of (is_duplicate: bool, content_hash: str).
        """
        r = self._get_redis()
        content_hash = self.compute_hash(headline)
        key = self._make_key(content_hash)

        try:
            # SETNX-like behavior: SET with NX flag
            # Returns True if the key was set (new), None if it already existed
            was_set = await r.set(key, "1", ex=self._ttl, nx=True)
            is_dup = was_set is None
            return is_dup, content_hash
        except Exception as e:
            logger.error("Redis dedup check_and_mark failed: %s", e)
            return False, content_hash

    async def deduplicate_batch(
        self, articles: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Deduplicate a batch of articles.

        Checks each article against Redis and marks new ones as seen.
        Adds 'content_hash' field to each non-duplicate article.

        Returns:
            Tuple of (unique_articles, duplicate_count).
        """
        unique: list[dict[str, Any]] = []
        dup_count = 0

        for article in articles:
            headline = article.get("headline", "")
            if not headline:
                continue

            is_dup, content_hash = await self.check_and_mark(headline)
            if is_dup:
                dup_count += 1
                logger.debug(
                    "Duplicate: '%.60s' (hash=%s...)",
                    headline, content_hash[:12],
                )
                continue

            article["content_hash"] = content_hash
            unique.append(article)

        if dup_count > 0:
            logger.info(
                "Dedup: %d unique, %d duplicates removed (batch of %d)",
                len(unique), dup_count, len(articles),
            )

        return unique, dup_count

    async def get_stats(self) -> dict[str, int]:
        """Return dedup statistics from Redis."""
        r = self._get_redis()
        try:
            pattern = f"{self._key_prefix}*"
            count = 0
            async for _ in r.scan_iter(match=pattern, count=1000):
                count += 1
            return {"tracked_hashes": count}
        except Exception as e:
            logger.error("Redis dedup stats failed: %s", e)
            return {"tracked_hashes": -1}

    async def clear(self) -> int:
        """Clear all dedup entries from Redis. Returns count of deleted keys."""
        r = self._get_redis()
        try:
            pattern = f"{self._key_prefix}*"
            keys: list[str] = []
            async for key in r.scan_iter(match=pattern, count=1000):
                keys.append(key)
            if keys:
                deleted = await r.delete(*keys)
                logger.info("Cleared %d dedup entries", deleted)
                return deleted
            return 0
        except Exception as e:
            logger.error("Redis dedup clear failed: %s", e)
            return 0
