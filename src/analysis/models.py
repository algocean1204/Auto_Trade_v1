"""F2 AI 분석 -- 공용 Pydantic 모델이다."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RegimeParams(BaseModel):
    """레짐별 전략 파라미터이다."""

    take_profit: float
    trailing_stop: float
    max_hold_days: int
    position_multiplier: float
    allow_bull_entry: bool
    allow_bear_entry: bool
    prefer_inverse: bool


class ClassifiedNews(BaseModel):
    """분류된 뉴스이다."""

    title: str
    content: str
    url: str
    source: str
    published_at: datetime
    impact_score: float  # 0.0~1.0
    direction: str  # bullish/bearish/neutral
    category: str  # macro/earnings/policy/sector/geopolitical
    tickers_affected: list[str] = []
    reasoning: str = ""
    # 단타 트레이딩 전용 필드이다
    time_sensitivity: str = "analysis"  # breaking/developing/analysis/background
    actionability: str = "informational"  # immediate/watch/informational
    leveraged_etf_impact: str = ""  # SOXL/QLD/TQQQ 등 2X ETF 영향 한줄 요약


class MarketRegime(BaseModel):
    """시장 레짐 판별 결과이다."""

    regime_type: str  # strong_bull/mild_bull/sideways/mild_bear/crash
    vix: float
    params: RegimeParams


class ComprehensiveReport(BaseModel):
    """종합 분석 보고서이다."""

    signals: list[dict]
    confidence: float
    recommendations: list[str]
    regime_assessment: str
    risk_level: str
    timestamp: datetime


class TradingDecision(BaseModel):
    """매매 판단 결과이다."""

    action: str  # buy/sell/hold
    ticker: str
    confidence: float
    size_pct: float
    reason: str
    direction: str = "bull"


class OvernightDecision(BaseModel):
    """오버나이트 판단이다."""

    ticker: str
    action: str  # hold/liquidate
    reason: str


class AnalysisSummary(BaseModel):
    """연속 분석 결과이다."""

    issues: list[str]
    signals: list[dict]
    timestamp: datetime


class KeyNews(BaseModel):
    """핵심 뉴스이다."""

    title: str
    impact_score: float
    direction: str
    category: str
    tickers_affected: list[str]
    summary: str
    source: str = ""


class FeedbackReport(BaseModel):
    """피드백 보고서이다."""

    summary: dict
    lessons: list[str]
    suggestions: list[str]


class ThemeSummary(BaseModel):
    """테마 요약이다."""

    theme: str
    frequency: int
    trend: str  # rising/stable/declining


class TranslatedNews(BaseModel):
    """번역된 뉴스이다."""

    original_title: str
    translated_title: str
    translated_content: str
    source_language: str


class TickerProfile(BaseModel):
    """티커 종합 프로파일이다."""

    ticker: str
    news_sentiment: float
    indicator_summary: dict
    analysis_text: str
    timestamp: datetime


class AnalysisContext(BaseModel):
    """분석 컨텍스트이다."""

    news_summary: str
    indicators: dict
    regime: str
    positions: list[dict]
    market_data: dict = {}


class PortfolioState(BaseModel):
    """포트폴리오 상태이다."""

    positions: list[dict]
    cash_available: float
    total_value: float
    daily_pnl: float = 0.0


class SituationTimelineEntry(BaseModel):
    """상황 타임라인 개별 항목이다."""

    timestamp: datetime
    headline: str
    summary: str
    source: str


class OngoingSituation(BaseModel):
    """진행 중인 장기 이슈 메타데이터이다."""

    situation_id: str
    name: str
    category: str  # geopolitical/macro/policy
    status: str  # escalating/stable/de_escalating/resolved
    first_seen: datetime
    last_updated: datetime
    article_count: int = 0


class SituationDetectionResult(BaseModel):
    """Claude 상황 감지 결과이다."""

    situation_id: str
    name: str
    category: str
    status: str
    matched_news_titles: list[str]


class SituationReport(BaseModel):
    """텔레그램 전송용 상황 보고서이다."""

    situation_id: str
    name: str
    status: str
    new_entries: list[SituationTimelineEntry]
    full_timeline_count: int
    assessment: str
