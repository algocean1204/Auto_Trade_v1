"""
Crawl result quality verifier.

Builds verification prompts for Claude Sonnet to validate crawl quality.
The actual Claude API call is handled by the analysis module -- this module
only generates the prompt and parses the response.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CrawlVerifier:
    """Verifies crawl quality using Claude Sonnet (prompt generation only).

    The Claude client is in a separate module (src/analysis/claude_client.py),
    so this class only builds the verification prompt and parses the result.
    The orchestrator (scheduler or API handler) calls Claude and passes
    the response back to parse_verification_result().
    """

    # Minimum thresholds for a passing crawl
    MIN_SOURCES_RATIO = 0.5     # At least 50% of sources must return data
    MIN_ARTICLES_COUNT = 10     # At least 10 total articles
    MAX_DUP_RATIO = 0.7         # No more than 70% duplicates

    def build_verification_prompt(self, crawl_result: dict[str, Any]) -> str:
        """Build a Claude prompt to verify crawl result quality.

        Args:
            crawl_result: The dict returned by CrawlEngine.run().

        Returns:
            A structured prompt string for Claude Sonnet.
        """
        source_stats = crawl_result.get("source_stats", {})
        total_raw = crawl_result.get("total_raw", 0)
        duplicates_removed = crawl_result.get("duplicates_removed", 0)
        kept = crawl_result.get("kept", 0)
        uncertain = crawl_result.get("uncertain", 0)
        discarded = crawl_result.get("discarded", 0)
        saved = crawl_result.get("saved", 0)
        mode = crawl_result.get("mode", "unknown")

        # Analyze per-source health
        sources_with_data = sum(
            1 for stats in source_stats.values()
            if stats.get("raw", 0) > 0
        )
        total_sources = len(source_stats)
        failed_sources = [
            key for key, stats in source_stats.items()
            if stats.get("raw", 0) == 0
        ]

        prompt = f"""Analyze the following crawl result and provide a quality assessment.

## Crawl Summary
- Mode: {mode}
- Total raw articles: {total_raw}
- Duplicates removed: {duplicates_removed}
- After dedup: {total_raw - duplicates_removed}
- Kept by filter: {kept}
- Uncertain (needs AI review): {uncertain}
- Discarded by filter: {discarded}
- Saved to database: {saved}

## Source Health
- Total sources configured: {total_sources}
- Sources with data: {sources_with_data}
- Failed sources: {', '.join(failed_sources) if failed_sources else 'None'}

## Per-Source Breakdown
{json.dumps(source_stats, indent=2)}

## Quality Check Criteria
1. Source coverage: Are critical sources (Reuters, Bloomberg, WSJ, Fed, SEC) returning data?
2. Volume: Is the article count reasonable for the time window?
3. Duplication rate: Is the dedup ratio healthy (< 70%)?
4. Filter balance: Is the keep/discard ratio reasonable?
5. Data freshness: Are articles recent enough?

## Instructions
Respond with a JSON object:
{{
  "overall_score": <float 0-100>,
  "grade": "<S/A/B/C/D/F>",
  "issues": ["<issue1>", "<issue2>", ...],
  "recommendations": ["<rec1>", "<rec2>", ...],
  "critical_source_status": {{
    "reuters": "<ok/missing/error>",
    "bloomberg_rss": "<ok/missing/error>",
    "wsj_rss": "<ok/missing/error>",
    "fed_announcements": "<ok/missing/error>",
    "sec_edgar": "<ok/missing/error>"
  }},
  "pass": <true/false>
}}

Grade scale: S(95+), A(85+), B(75+), C(65+), D(50+), F(<50)
Pass requires grade B or above."""

        return prompt

    def parse_verification_result(
        self, claude_response: str
    ) -> dict[str, Any]:
        """Parse Claude's verification response into a structured result.

        Args:
            claude_response: Raw text response from Claude.

        Returns:
            Parsed verification result dict.
        """
        # Try to extract JSON from the response
        result = self._extract_json(claude_response)

        if result is None:
            logger.warning("Could not parse verification response as JSON")
            return {
                "overall_score": 0.0,
                "grade": "F",
                "issues": ["Verification response could not be parsed"],
                "recommendations": [],
                "pass": False,
                "raw_response": claude_response[:2000],
            }

        # Validate required fields
        result.setdefault("overall_score", 0.0)
        result.setdefault("grade", "F")
        result.setdefault("issues", [])
        result.setdefault("recommendations", [])
        result.setdefault("pass", False)

        return result

    def quick_verify(self, crawl_result: dict[str, Any]) -> dict[str, Any]:
        """Perform a quick local verification without Claude.

        Checks basic thresholds that do not require AI analysis.
        Use this for fast feedback; use build_verification_prompt() +
        parse_verification_result() for thorough AI-powered verification.
        """
        source_stats = crawl_result.get("source_stats", {})
        total_raw = crawl_result.get("total_raw", 0)
        duplicates_removed = crawl_result.get("duplicates_removed", 0)
        saved = crawl_result.get("saved", 0)

        issues: list[str] = []
        total_sources = len(source_stats)
        sources_with_data = sum(
            1 for stats in source_stats.values()
            if stats.get("raw", 0) > 0
        )

        # Check source coverage
        if total_sources > 0:
            source_ratio = sources_with_data / total_sources
            if source_ratio < self.MIN_SOURCES_RATIO:
                issues.append(
                    f"Low source coverage: {sources_with_data}/{total_sources} "
                    f"({source_ratio:.0%})"
                )

        # Check article volume
        if total_raw < self.MIN_ARTICLES_COUNT:
            issues.append(
                f"Low article count: {total_raw} (min {self.MIN_ARTICLES_COUNT})"
            )

        # Check duplication ratio
        if total_raw > 0:
            dup_ratio = duplicates_removed / total_raw
            if dup_ratio > self.MAX_DUP_RATIO:
                issues.append(
                    f"High duplication rate: {dup_ratio:.0%}"
                )

        # Check critical sources
        critical = ["reuters", "bloomberg_rss", "wsj_rss", "fed_announcements"]
        for src in critical:
            if src in source_stats and source_stats[src].get("raw", 0) == 0:
                issues.append(f"Critical source '{src}' returned no data")

        passed = len(issues) == 0
        score = max(0.0, 100.0 - len(issues) * 15.0)

        return {
            "overall_score": score,
            "grade": self._score_to_grade(score),
            "issues": issues,
            "pass": passed,
            "verified_at": datetime.now(tz=timezone.utc).isoformat(),
            "method": "quick_local",
        }

    @staticmethod
    def _score_to_grade(score: float) -> str:
        """Convert numeric score to letter grade."""
        if score >= 95:
            return "S"
        if score >= 85:
            return "A"
        if score >= 75:
            return "B"
        if score >= 65:
            return "C"
        if score >= 50:
            return "D"
        return "F"

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract JSON object from text that may contain markdown fences."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding first { ... } block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None
