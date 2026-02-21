"""
Crawler subsystem for the AI Auto-Trading System V2.

Provides asynchronous crawling from 31+ global news and data sources,
with deduplication, rule-based filtering, checkpoint management,
and AI context building for Claude prompt injection.
"""

from src.crawler.ai_context_builder import build_ai_context, build_ai_context_compact
from src.crawler.crawl_engine import CrawlEngine
from src.crawler.dedup import DedupChecker

__all__ = [
    "CrawlEngine",
    "DedupChecker",
    "build_ai_context",
    "build_ai_context_compact",
]
