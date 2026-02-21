"""
src.filter -- Rule-based news filtering module.

Provides fast, deterministic pre-filtering of crawled articles
before they are sent to Claude for deeper analysis.
"""

from src.filter.rule_filter import RuleBasedFilter
from src.filter.similarity_checker import SimilarityChecker

__all__ = ["RuleBasedFilter", "SimilarityChecker"]
