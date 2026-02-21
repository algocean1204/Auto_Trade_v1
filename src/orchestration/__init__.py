"""
오케스트레이션 패키지.

TradingSystem의 주요 루프/단계를 독립 모듈로 분리하여 main.py의 크기를 줄인다.
"""
from src.orchestration.news_pipeline import NewsPipeline

__all__ = [
    "NewsPipeline",
]
