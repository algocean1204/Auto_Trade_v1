"""DB ORM 모델 -- 16개 테이블의 SQLAlchemy 2.0 모델이다.

UUID PK, TIMESTAMP(timezone=True), server_default=text("(datetime('now'))") 컨벤션을 따른다.
SQLite(aiosqlite) 기반이다. Base는 database_gateway에서 가져온다.

Note: 미사용 11개 모델(FxRateRecord, SlippageLog, EmergencyEvent, CapitalGuardLog,
NotificationLog, RiskConfig, RiskEvent, BacktestResult, FearGreedHistory,
PredictionMarket, EtfUniverse)은 코드에서 import/사용되지 않아 제거했다.
Alembic 마이그레이션은 참조용으로 유지한다. 기존 DB 테이블은 무해하게 잔존한다.
"""
from __future__ import annotations

import uuid

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

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
    published_at = Column(DateTime(timezone=True), index=True)
    content_hash = Column(String, index=True)
    impact_score = Column(Float, default=0.0)
    direction = Column(String, default="neutral")
    category = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 2. 매매 기록 ──
class Trade(Base):
    __tablename__ = "trades"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    order_id = Column(String, default="")
    reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"), index=True)


# ── 3. 지표 이력 ──
class IndicatorHistory(Base):
    __tablename__ = "indicator_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, nullable=False, index=True)
    indicator_name = Column(String, nullable=False)
    value = Column(Float)
    recorded_at = Column(DateTime(timezone=True), index=True)
    metadata_ = Column("metadata", JSON, default=dict)


# ── 4. 전략 파라미터 변경 이력 ──
class StrategyParamHistory(Base):
    __tablename__ = "strategy_param_history"
    id = Column(String, primary_key=True, default=_uuid)
    param_name = Column(String, nullable=False)
    old_value = Column(String)
    new_value = Column(String)
    reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 5. 피드백 보고서 ──
class FeedbackReport(Base):
    __tablename__ = "feedback_reports"
    id = Column(String, primary_key=True, default=_uuid)
    report_type = Column(String, default="daily", index=True)
    report_date = Column(Date, index=True)
    content = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 6. 크롤링 체크포인트 ──
class CrawlCheckpoint(Base):
    __tablename__ = "crawl_checkpoints"
    id = Column(Integer, primary_key=True, autoincrement=True)
    checkpoint_at = Column(DateTime(timezone=True), nullable=False)
    total_articles = Column(Integer)
    source_stats = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 7. 대기 중 조정 ──
class PendingAdjustment(Base):
    __tablename__ = "pending_adjustments"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    adjustment_type = Column(String, nullable=False)
    value = Column(Float)
    applied = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 8. 세금 기록 ──
class TaxRecord(Base):
    __tablename__ = "tax_records"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    gain_usd = Column(Float, default=0.0)
    tax_krw = Column(Float, default=0.0)
    fx_rate = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 9. 벤치마크 스냅샷 ──
class BenchmarkSnapshot(Base):
    __tablename__ = "benchmark_snapshots"
    id = Column(String, primary_key=True, default=_uuid)
    benchmark = Column(String, nullable=False)
    value = Column(Float)
    portfolio_value = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 10. 수익 목표 ──
class ProfitTarget(Base):
    __tablename__ = "profit_targets"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    target_pct = Column(Float, nullable=False)
    achieved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 11. 일일 PnL ──
class DailyPnlLog(Base):
    __tablename__ = "daily_pnl_log"
    id = Column(String, primary_key=True, default=_uuid)
    date = Column(String, nullable=False, index=True)
    pnl_amount = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    equity = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 12. 과거 분석 ──
class HistoricalAnalysis(Base):
    __tablename__ = "historical_analyses"
    id = Column(String, primary_key=True, default=_uuid)
    analysis_type = Column(String, nullable=False)
    ticker = Column(String, default="")
    result = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 13. 분석 진행 ──
class HistoricalAnalysisProgress(Base):
    __tablename__ = "historical_analysis_progress"
    id = Column(String, primary_key=True, default=_uuid)
    task_name = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress_pct = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 14. 틱 데이터 ──
class TickData(Base):
    __tablename__ = "tick_data"
    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Integer, default=0)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 15. RAG 문서 ──
class RagDocument(Base):
    __tablename__ = "rag_documents"
    id = Column(String, primary_key=True, default=_uuid)
    doc_type = Column(String, nullable=False)
    title = Column(String, default="")
    content = Column(Text)
    embedding_id = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=text("(datetime('now'))"))


# ── 16. 유니버스 설정 ──
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
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(datetime('now'))")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(datetime('now'))"),
        # SQLite는 서버사이드 onupdate를 지원하지 않으므로 Python-side 콜백으로 처리한다
        onupdate=lambda: datetime.now(timezone.utc),
    )
