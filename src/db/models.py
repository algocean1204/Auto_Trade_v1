"""DB ORM 모델 -- 26개 테이블의 SQLAlchemy 2.0 모델이다.

UUID PK, TIMESTAMP(timezone=True), server_default=func.now() 컨벤션을 따른다.
Base는 database_gateway에서 가져온다.
"""
from __future__ import annotations

import uuid

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.common.database_gateway import Base


def _uuid() -> str:
    """새 UUID 문자열을 생성한다."""
    return str(uuid.uuid4())


# ── 1. 수집된 기사 ──
class Article(Base):
    __tablename__ = "articles"
    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    content = Column(Text)
    url = Column(String, unique=True)
    source = Column(String)
    published_at = Column(DateTime(timezone=True))
    content_hash = Column(String, index=True)
    impact_score = Column(Float, default=0.0)
    direction = Column(String, default="neutral")
    category = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 2. 매매 기록 ──
class Trade(Base):
    __tablename__ = "trades"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    order_id = Column(String, default="")
    reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 3. ETF 유니버스 ──
class EtfUniverse(Base):
    __tablename__ = "etf_universe"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, unique=True, nullable=False)
    name = Column(String, default="")
    leverage = Column(Float, default=2.0)
    exchange = Column(String, default="NAS")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 4. 지표 이력 ──
class IndicatorHistory(Base):
    __tablename__ = "indicator_history"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False, index=True)
    indicator_name = Column(String, nullable=False)
    value = Column(Float)
    metadata_ = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 5. 전략 파라미터 변경 이력 ──
class StrategyParamHistory(Base):
    __tablename__ = "strategy_param_history"
    id = Column(String, primary_key=True, default=_uuid)
    param_name = Column(String, nullable=False)
    old_value = Column(String)
    new_value = Column(String)
    reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 6. 피드백 보고서 ──
class FeedbackReport(Base):
    __tablename__ = "feedback_reports"
    id = Column(String, primary_key=True, default=_uuid)
    report_type = Column(String, default="daily")
    content = Column(JSON, default={})
    summary = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 7. 크롤링 체크포인트 ──
class CrawlCheckpoint(Base):
    __tablename__ = "crawl_checkpoints"
    id = Column(String, primary_key=True, default=_uuid)
    source = Column(String, nullable=False, unique=True)
    last_url = Column(String, default="")
    last_published = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 8. 대기 중 조정 ──
class PendingAdjustment(Base):
    __tablename__ = "pending_adjustments"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    adjustment_type = Column(String, nullable=False)
    value = Column(Float)
    applied = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 9. 세금 기록 ──
class TaxRecord(Base):
    __tablename__ = "tax_records"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    gain_usd = Column(Float, default=0.0)
    tax_krw = Column(Float, default=0.0)
    fx_rate = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 10. 환율 기록 ──
class FxRateRecord(Base):
    __tablename__ = "fx_rates"
    id = Column(String, primary_key=True, default=_uuid)
    usd_krw = Column(Float, nullable=False)
    source = Column(String, default="kis")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 11. 슬리피지 기록 ──
class SlippageLog(Base):
    __tablename__ = "slippage_log"
    id = Column(String, primary_key=True, default=_uuid)
    order_id = Column(String, default="")
    slippage_pct = Column(Float, default=0.0)
    slippage_amount = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 12. 긴급 이벤트 ──
class EmergencyEvent(Base):
    __tablename__ = "emergency_events"
    id = Column(String, primary_key=True, default=_uuid)
    event_type = Column(String, nullable=False)
    reason = Column(Text, default="")
    action_taken = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 13. 벤치마크 스냅샷 ──
class BenchmarkSnapshot(Base):
    __tablename__ = "benchmark_snapshots"
    id = Column(String, primary_key=True, default=_uuid)
    benchmark = Column(String, nullable=False)
    value = Column(Float)
    portfolio_value = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 14. 자본 보호 로그 ──
class CapitalGuardLog(Base):
    __tablename__ = "capital_guard_log"
    id = Column(String, primary_key=True, default=_uuid)
    guard_type = Column(String, nullable=False)
    trigger_value = Column(Float)
    action = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 15. 알림 로그 ──
class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(String, primary_key=True, default=_uuid)
    channel = Column(String, default="telegram")
    event_type = Column(String, nullable=False)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 16. 수익 목표 ──
class ProfitTarget(Base):
    __tablename__ = "profit_targets"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    target_pct = Column(Float, nullable=False)
    achieved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 17. 일일 PnL ──
class DailyPnlLog(Base):
    __tablename__ = "daily_pnl_log"
    id = Column(String, primary_key=True, default=_uuid)
    date = Column(String, nullable=False, index=True)
    pnl_amount = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    equity = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 18. 리스크 설정 ──
class RiskConfig(Base):
    __tablename__ = "risk_config"
    id = Column(String, primary_key=True, default=_uuid)
    param_name = Column(String, unique=True, nullable=False)
    param_value = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 19. 리스크 이벤트 ──
class RiskEvent(Base):
    __tablename__ = "risk_events"
    id = Column(String, primary_key=True, default=_uuid)
    event_type = Column(String, nullable=False)
    severity = Column(String, default="medium")
    detail = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 20. 백테스트 결과 ──
class BacktestResult(Base):
    __tablename__ = "backtest_results"
    id = Column(String, primary_key=True, default=_uuid)
    strategy_name = Column(String, nullable=False)
    params = Column(JSON, default={})
    metrics = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 21. Fear&Greed 이력 ──
class FearGreedHistory(Base):
    __tablename__ = "fear_greed_history"
    id = Column(String, primary_key=True, default=_uuid)
    index_value = Column(Float, nullable=False)
    label = Column(String, default="neutral")
    source = Column(String, default="cnn")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 22. 예측시장 ──
class PredictionMarket(Base):
    __tablename__ = "prediction_markets"
    id = Column(String, primary_key=True, default=_uuid)
    market_name = Column(String, nullable=False)
    probability = Column(Float)
    source = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 23. 과거 분석 ──
class HistoricalAnalysis(Base):
    __tablename__ = "historical_analyses"
    id = Column(String, primary_key=True, default=_uuid)
    analysis_type = Column(String, nullable=False)
    ticker = Column(String, default="")
    result = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 24. 분석 진행 ──
class HistoricalAnalysisProgress(Base):
    __tablename__ = "historical_analysis_progress"
    id = Column(String, primary_key=True, default=_uuid)
    task_name = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress_pct = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 25. 틱 데이터 ──
class TickData(Base):
    __tablename__ = "tick_data"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Integer, default=0)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 26. RAG 문서 ──
class RagDocument(Base):
    __tablename__ = "rag_documents"
    id = Column(String, primary_key=True, default=_uuid)
    doc_type = Column(String, nullable=False)
    title = Column(String, default="")
    content = Column(Text)
    embedding_id = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── 27. 유니버스 설정 ──
class UniverseConfig(Base):
    """유니버스 티커 설정 테이블이다. DB가 source of truth로 동작한다."""

    __tablename__ = "universe_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="AMS")
    sector: Mapped[str] = mapped_column(String(50), nullable=False, default="broad_market")
    leverage: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    is_inverse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pair_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
