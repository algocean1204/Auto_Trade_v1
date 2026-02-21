"""
Headline similarity checker for duplicate detection.

Uses character-level n-gram Jaccard similarity to detect near-duplicate
headlines. Articles with high similarity to recently seen headlines are
flagged as 'uncertain' so Claude can make the final call.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class SimilarityChecker:
    """Detects near-duplicate headlines using n-gram Jaccard similarity."""

    def __init__(
        self,
        threshold: float = 0.6,
        window_hours: int = 6,
        ngram_size: int = 3,
        max_history: int = 5000,
    ) -> None:
        self.threshold: float = threshold
        self.window_hours: int = window_hours
        self.ngram_size: int = ngram_size
        self.max_history: int = max_history
        # Ring buffer: each entry is (normalized_headline, ngram_set, timestamp)
        self._history: deque[tuple[str, set[str], datetime]] = deque(
            maxlen=max_history
        )
        logger.info(
            "SimilarityChecker initialized: threshold=%.2f, window=%dh, ngram=%d",
            threshold,
            window_hours,
            ngram_size,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text

    def _ngrams(self, text: str) -> set[str]:
        """Generate character-level n-grams from normalized text."""
        if len(text) < self.ngram_size:
            return {text} if text else set()
        return {
            text[i : i + self.ngram_size]
            for i in range(len(text) - self.ngram_size + 1)
        }

    @staticmethod
    def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
        """Compute Jaccard similarity between two sets."""
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _prune_old_entries(self, now: datetime) -> None:
        """Remove entries outside the time window from the front of the deque."""
        from datetime import timedelta

        cutoff = now - timedelta(hours=self.window_hours)
        while self._history and self._history[0][2] < cutoff:
            self._history.popleft()

    def is_similar(
        self,
        headline: str,
        published_at: Optional[datetime] = None,
    ) -> tuple[bool, float, Optional[str]]:
        """
        Check if a headline is similar to any recently seen headline.

        Returns:
            (is_duplicate, highest_similarity_score, matched_headline_or_None)
        """
        now = published_at or datetime.now(tz=timezone.utc)
        self._prune_old_entries(now)

        normalized = self._normalize(headline)
        ngram_set = self._ngrams(normalized)

        best_score: float = 0.0
        best_match: Optional[str] = None

        for stored_headline, stored_ngrams, _ in self._history:
            score = self.jaccard_similarity(ngram_set, stored_ngrams)
            if score > best_score:
                best_score = score
                best_match = stored_headline

        is_dup = best_score >= self.threshold

        if is_dup:
            logger.debug(
                "Duplicate detected (%.2f): '%s' ~ '%s'",
                best_score,
                headline[:80],
                best_match[:80] if best_match else "",
            )

        # Always add to history so future articles can be checked against it
        self._history.append((normalized, ngram_set, now))

        return is_dup, best_score, best_match

    def add_headline(
        self,
        headline: str,
        published_at: Optional[datetime] = None,
    ) -> None:
        """Manually add a headline to history without checking similarity."""
        now = published_at or datetime.now(tz=timezone.utc)
        normalized = self._normalize(headline)
        ngram_set = self._ngrams(normalized)
        self._history.append((normalized, ngram_set, now))

    def clear(self) -> None:
        """Clear all stored headlines."""
        self._history.clear()
        logger.info("SimilarityChecker history cleared")

    @property
    def history_size(self) -> int:
        """Number of headlines currently stored."""
        return len(self._history)
