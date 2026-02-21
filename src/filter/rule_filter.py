"""
Rule-based news filter.

Removes obviously irrelevant articles before sending them to Claude,
reducing API cost and latency. Each article is classified as:

  - keep:      Clearly relevant to financial markets / ETF trading
  - discard:   Spam, too old, wrong language, or unrelated
  - uncertain: Possibly duplicate or borderline -- let Claude decide
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from src.filter.similarity_checker import SimilarityChecker

logger = logging.getLogger(__name__)

FilterVerdict = Literal["keep", "discard", "uncertain"]

_DEFAULT_CONFIG_PATH = str(Path(__file__).parent / "filter_config.json")


class RuleBasedFilter:
    """Deterministic, keyword-driven pre-filter for crawled news articles."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config: dict[str, Any] = self._load_config(
            config_path or _DEFAULT_CONFIG_PATH
        )
        self._similarity_checker = SimilarityChecker(
            threshold=self.config.get("similarity_threshold", 0.6),
            window_hours=self.config.get("similarity_window_hours", 6),
        )
        # Pre-compile patterns for performance
        self._spam_patterns: list[re.Pattern[str]] = [
            re.compile(re.escape(kw), re.IGNORECASE)
            for kw in self.config.get("spam_keywords", [])
        ]
        self._financial_patterns: list[re.Pattern[str]] = [
            re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            for kw in self.config.get("financial_keywords", [])
        ]
        self._macro_patterns: list[re.Pattern[str]] = [
            re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            for kw in self.config.get("macro_keywords", [])
        ]
        # Ticker patterns need word boundaries to avoid false positives
        self._etf_ticker_set: set[str] = {
            t.upper() for t in self.config.get("etf_tickers", [])
        }
        self._company_ticker_set: set[str] = {
            t.upper() for t in self.config.get("major_companies", [])
        }
        # Flatten sector keywords into compiled patterns
        self._sector_patterns: list[re.Pattern[str]] = []
        for keywords in self.config.get("sector_keywords", {}).values():
            for kw in keywords:
                self._sector_patterns.append(
                    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                )

        logger.info(
            "RuleBasedFilter initialized: %d spam, %d financial, %d macro, "
            "%d ETF tickers, %d company tickers, %d sector patterns",
            len(self._spam_patterns),
            len(self._financial_patterns),
            len(self._macro_patterns),
            len(self._etf_ticker_set),
            len(self._company_ticker_set),
            len(self._sector_patterns),
        )

    @staticmethod
    def _load_config(config_path: str) -> dict[str, Any]:
        """Load filter configuration from JSON file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(
                "Config file not found at %s, using empty config", config_path
            )
            return {}
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        logger.info("Filter config loaded from %s", config_path)
        return config

    def _check_age(self, published_at: datetime) -> Optional[FilterVerdict]:
        """Discard articles older than max_age_hours."""
        max_hours = self.config.get("max_age_hours", 24)
        now = datetime.now(tz=timezone.utc)
        # Ensure published_at is timezone-aware
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age = now - published_at
        if age > timedelta(hours=max_hours):
            logger.debug(
                "Age filter: article is %.1f hours old (max %d)",
                age.total_seconds() / 3600,
                max_hours,
            )
            return "discard"
        return None

    def _check_language(self, language: str) -> Optional[FilterVerdict]:
        """Discard articles in unsupported languages."""
        supported = self.config.get("supported_languages", ["en", "ko"])
        lang_lower = language.lower().strip()
        # Handle both "en" and "en-US" style codes
        lang_prefix = lang_lower.split("-")[0].split("_")[0]
        if lang_prefix not in supported:
            logger.debug(
                "Language filter: '%s' not in %s", language, supported
            )
            return "discard"
        return None

    def _check_spam(self, text: str) -> Optional[FilterVerdict]:
        """Discard articles containing spam/advertising keywords."""
        for pattern in self._spam_patterns:
            if pattern.search(text):
                logger.debug(
                    "Spam filter: matched '%s'", pattern.pattern[:40]
                )
                return "discard"
        return None

    def _extract_tickers_from_text(self, text: str) -> set[str]:
        """Extract potential stock tickers (1-5 uppercase letters) from text."""
        # Match standalone uppercase sequences that look like tickers
        return set(re.findall(r"\b([A-Z]{1,5})\b", text))

    def _check_relevance(self, text: str) -> Optional[FilterVerdict]:
        """
        Check financial relevance. Returns 'keep' if any relevance signal
        is found, None otherwise (caller decides what to do with no match).
        """
        # Priority 1: ETF ticker mentioned
        found_tickers = self._extract_tickers_from_text(text)
        etf_matches = found_tickers & self._etf_ticker_set
        if etf_matches:
            logger.debug("Relevance: ETF ticker(s) found: %s", etf_matches)
            return "keep"

        # Priority 2: Major company ticker mentioned
        company_matches = found_tickers & self._company_ticker_set
        if company_matches:
            logger.debug(
                "Relevance: company ticker(s) found: %s", company_matches
            )
            return "keep"

        # Priority 3: Macro keywords (Federal Reserve, rate cut, etc.)
        for pattern in self._macro_patterns:
            if pattern.search(text):
                logger.debug(
                    "Relevance: macro keyword '%s'", pattern.pattern[:40]
                )
                return "keep"

        # Priority 4: General financial keywords
        for pattern in self._financial_patterns:
            if pattern.search(text):
                logger.debug(
                    "Relevance: financial keyword '%s'", pattern.pattern[:40]
                )
                return "keep"

        # Priority 5: Sector keywords
        for pattern in self._sector_patterns:
            if pattern.search(text):
                logger.debug(
                    "Relevance: sector keyword '%s'", pattern.pattern[:40]
                )
                return "keep"

        return None

    def _check_similarity(
        self, headline: str, published_at: datetime
    ) -> Optional[FilterVerdict]:
        """Flag near-duplicate headlines as uncertain."""
        is_dup, score, match = self._similarity_checker.is_similar(
            headline, published_at
        )
        if is_dup:
            logger.debug(
                "Similarity filter: '%.60s' ~ '%.60s' (score=%.2f)",
                headline,
                match or "",
                score,
            )
            return "uncertain"
        return None

    def filter(self, article: dict[str, Any]) -> FilterVerdict:
        """
        Classify a single article.

        Args:
            article: Dictionary with keys:
                - headline (str): Article headline (required)
                - content (str, optional): Article body text
                - source (str): News source identifier
                - published_at (datetime): Publication timestamp
                - language (str): Language code (e.g. "en", "ko")
                - url (str): Article URL

        Returns:
            "keep", "discard", or "uncertain"
        """
        headline: str = article.get("headline", "")
        content: str = article.get("content", "")
        language: str = article.get("language", "en")
        published_at: datetime = article.get(
            "published_at", datetime.now(tz=timezone.utc)
        )
        source: str = article.get("source", "unknown")

        # Combine headline and content for text-based checks
        full_text = f"{headline} {content}".strip()

        if not headline:
            logger.debug("Empty headline from source=%s, discarding", source)
            return "discard"

        # Step 1: Time filter
        verdict = self._check_age(published_at)
        if verdict:
            return verdict

        # Step 2: Language filter
        verdict = self._check_language(language)
        if verdict:
            return verdict

        # Step 3: Spam/ad filter
        verdict = self._check_spam(full_text)
        if verdict:
            return verdict

        # Step 4: Similarity / duplicate check (runs before relevance so
        # that near-duplicate financial articles are flagged as uncertain
        # for Claude to decide, rather than auto-kept)
        verdict = self._check_similarity(headline, published_at)
        if verdict:
            return verdict

        # Step 5: Relevance filter (financial keywords, tickers, etc.)
        verdict = self._check_relevance(full_text)
        if verdict:
            return verdict

        # No relevance signals found -> discard
        logger.debug(
            "No relevance signal for '%.60s' from %s", headline, source
        )
        return "discard"

    def batch_filter(
        self, articles: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Filter a batch of articles.

        Returns:
            {"keep": [...], "discard": [...], "uncertain": [...]}
        """
        results: dict[str, list[dict[str, Any]]] = {
            "keep": [],
            "discard": [],
            "uncertain": [],
        }

        for article in articles:
            verdict = self.filter(article)
            results[verdict].append(article)

        logger.info(
            "Batch filter results: %d keep, %d discard, %d uncertain "
            "(total %d)",
            len(results["keep"]),
            len(results["discard"]),
            len(results["uncertain"]),
            len(articles),
        )
        return results

    def get_stats(self) -> dict[str, Any]:
        """Return current filter state for monitoring."""
        return {
            "similarity_history_size": self._similarity_checker.history_size,
            "config_keys": list(self.config.keys()),
            "etf_tickers_count": len(self._etf_ticker_set),
            "company_tickers_count": len(self._company_ticker_set),
        }

    def reset_similarity_history(self) -> None:
        """Clear the similarity checker's headline history."""
        self._similarity_checker.clear()
