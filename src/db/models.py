"""
SQLAlchemy ORM models for the AI Auto-Trading System V2.
Maps to the schema defined in db/init.sql.
"""

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict
    )
    embedding = mapped_column(Vector(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    source: Mapped[str | None] = mapped_column(String(50))
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0)

    __table_args__ = (
        Index("idx_rag_documents_doc_type", "doc_type"),
        Index("idx_rag_documents_ticker", "ticker"),
        Index("idx_rag_documents_created_at", "created_at"),
    )


class EtfUniverse(Base):
    __tablename__ = "etf_universe"

    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    leverage: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    underlying: Mapped[str | None] = mapped_column(String(100))
    expense_ratio: Mapped[float | None] = mapped_column(Float)
    avg_daily_volume: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    min_volume_threshold: Mapped[int] = mapped_column(Integer, default=100000)
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    added_by: Mapped[str] = mapped_column(String(20), default="system")
    notes: Mapped[str | None] = mapped_column(Text)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float)
    entry_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    exit_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    pnl_pct: Mapped[float | None] = mapped_column(Float)
    pnl_amount: Mapped[float | None] = mapped_column(Float)
    hold_minutes: Mapped[int | None] = mapped_column(Integer)
    exit_reason: Mapped[str | None] = mapped_column(String(50))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_signals: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    market_regime: Mapped[str | None] = mapped_column(String(20))
    post_analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    tax_records: Mapped[list["TaxRecord"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )
    slippage_logs: Mapped[list["SlippageLog"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_trades_ticker", "ticker"),
        Index("idx_trades_entry_at", "entry_at"),
        Index("idx_trades_exit_reason", "exit_reason"),
        Index("idx_trades_created_at", "created_at"),
    )


class IndicatorHistory(Base):
    __tablename__ = "indicator_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict
    )

    __table_args__ = (
        Index(
            "idx_indicator_history_composite",
            "ticker",
            "indicator_name",
            "recorded_at",
        ),
    )


class StrategyParamHistory(Base):
    __tablename__ = "strategy_param_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    param_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[float | None] = mapped_column(Float)
    new_value: Mapped[float] = mapped_column(Float, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(20))
    applied_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_strategy_param_history_param", "param_name"),
        Index("idx_strategy_param_history_applied", "applied_at"),
    )


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_feedback_reports_type_date", "report_type", "report_date"),
    )


class CrawlCheckpoint(Base):
    __tablename__ = "crawl_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkpoint_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    total_articles: Mapped[int | None] = mapped_column(Integer)
    source_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    language: Mapped[str] = mapped_column(String(5), default="en")
    tickers_mentioned: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    classification: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    crawled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    headline_kr: Mapped[str | None] = mapped_column(Text, nullable=True)  # 한국어 번역 헤드라인
    summary_ko: Mapped[str | None] = mapped_column(Text, nullable=True)  # 한국어 요약 (2-3줄)
    companies_impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # {"AAPL": "영향 분석 2줄"}

    __table_args__ = (
        Index("idx_articles_source_crawled", "source", "crawled_at"),
        Index("idx_articles_is_processed", "is_processed"),
        Index("idx_articles_content_hash", "content_hash"),
        Index("idx_articles_published_at", "published_at"),
    )


class PendingAdjustment(Base):
    __tablename__ = "pending_adjustments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    param_name: Mapped[str] = mapped_column(String(50), nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_value: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("idx_pending_adjustments_status", "status"),
        Index("idx_pending_adjustments_created", "created_at"),
    )


class TaxRecord(Base):
    """거래별 세금 기록을 저장한다. 실현 손익과 환율 정보를 포함한다."""

    __tablename__ = "tax_records"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    trade_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    realized_gain_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_loss_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fx_rate_at_trade: Mapped[float] = mapped_column(Float, nullable=False)
    realized_gain_krw: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_loss_krw: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="양도소득세"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    trade: Mapped["Trade"] = relationship(back_populates="tax_records")

    __table_args__ = (
        Index("idx_tax_records_trade_id", "trade_id"),
        Index("idx_tax_records_year", "year"),
        Index("idx_tax_records_created_at", "created_at"),
    )


class FxRate(Base):
    """USD/KRW 환율 이력을 저장한다."""

    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    usd_krw_rate: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="KIS")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_fx_rates_timestamp", "timestamp"),
        Index("idx_fx_rates_source", "source"),
    )


class SlippageLog(Base):
    """체결 슬리피지를 기록한다. 예상 가격과 실제 체결 가격의 차이를 추적한다."""

    __tablename__ = "slippage_log"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    trade_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    expected_price: Mapped[float] = mapped_column(Float, nullable=False)
    actual_price: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_pct: Mapped[float] = mapped_column(Float, nullable=False)
    volume_at_fill: Mapped[int | None] = mapped_column(Integer)
    time_of_day: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    trade: Mapped["Trade"] = relationship(back_populates="slippage_logs")

    __table_args__ = (
        Index("idx_slippage_log_trade_id", "trade_id"),
        Index("idx_slippage_log_ticker", "ticker"),
        Index("idx_slippage_log_created_at", "created_at"),
    )


class EmergencyEvent(Base):
    """긴급 프로토콜 발동 이력을 기록한다."""

    __tablename__ = "emergency_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_value: Mapped[float | None] = mapped_column(Float)
    action_taken: Mapped[str] = mapped_column(Text, nullable=False)
    positions_affected: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_emergency_events_event_type", "event_type"),
        Index("idx_emergency_events_created_at", "created_at"),
    )


class BenchmarkSnapshot(Base):
    """AI 전략 수익률과 패시브 벤치마크(SPY, SSO)를 비교한다."""

    __tablename__ = "benchmark_snapshots"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="daily"
    )
    ai_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    spy_buyhold_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    sso_buyhold_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    cash_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_vs_spy_diff: Mapped[float] = mapped_column(Float, nullable=False)
    ai_vs_sso_diff: Mapped[float] = mapped_column(Float, nullable=False)
    consecutive_underperform_weeks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_benchmark_snapshots_date", "date"),
        Index("idx_benchmark_snapshots_period_type", "period_type"),
        Index("idx_benchmark_snapshots_created_at", "created_at"),
    )


class CapitalGuardLog(Base):
    """자본금 안전 검증 로그를 저장한다. safety_3set, balance_check, order_validation 등이다."""

    __tablename__ = "capital_guard_log"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    check_type: Mapped[str] = mapped_column(String(30), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_capital_guard_log_check_type", "check_type"),
        Index("idx_capital_guard_log_passed", "passed"),
        Index("idx_capital_guard_log_created_at", "created_at"),
    )


class NotificationLog(Base):
    """발송된 알림 이력을 기록한다. 텔레그램, 플러터 푸시 등 채널별로 추적한다."""

    __tablename__ = "notification_log"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_notification_log_channel", "channel"),
        Index("idx_notification_log_severity", "severity"),
        Index("idx_notification_log_sent_at", "sent_at"),
        Index("idx_notification_log_created_at", "created_at"),
    )


class ProfitTarget(Base):
    """월별 수익 목표를 관리한다. 실현/미실현 손익과 공격성 오버라이드를 포함한다."""

    __tablename__ = "profit_targets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    target_usd: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=300.00
    )
    realized_pnl: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    aggression_override: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_profit_targets_month", "month"),
    )


class DailyPnlLog(Base):
    """일별 손익을 기록한다. 실현/미실현 PnL, 거래 횟수, 공격성 수준을 포함한다."""

    __tablename__ = "daily_pnl_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    realized_pnl: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unrealized_pnl: Mapped[float | None] = mapped_column(Numeric(10, 2))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    aggression_level: Mapped[str | None] = mapped_column(String(20))
    target_daily: Mapped[float | None] = mapped_column(Numeric(10, 2))

    __table_args__ = (
        Index("idx_daily_pnl_log_date", "date"),
    )


class RiskConfig(Base):
    """리스크 관리 파라미터를 저장한다. key-value 형태로 각종 한도를 관리한다."""

    __tablename__ = "risk_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    param_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    param_value: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_risk_config_param_key", "param_key"),
    )


class RiskEvent(Base):
    """리스크 이벤트를 기록한다. 게이트 트리거, 손절, 쿨다운 등 리스크 발생 내역이다."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    gate_name: Mapped[str | None] = mapped_column(String(30))
    severity: Mapped[str | None] = mapped_column(String(10))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_risk_events_event_type", "event_type"),
        Index("idx_risk_events_severity", "severity"),
        Index("idx_risk_events_created_at", "created_at"),
    )


class BacktestResult(Base):
    """백테스트 실행 결과를 저장한다. 수익률, 드로다운, 샤프비율 등 주요 지표를 포함한다."""

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    total_return: Mapped[float | None] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[float | None] = mapped_column(Numeric(8, 4))
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(6, 3))
    win_rate: Mapped[float | None] = mapped_column(Numeric(5, 3))
    profit_factor: Mapped[float | None] = mapped_column(Numeric(6, 3))
    recommendation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_backtest_results_run_date", "run_date"),
        Index("idx_backtest_results_created_at", "created_at"),
    )


class FearGreedHistory(Base):
    """Fear & Greed 지수 이력을 저장한다. 7개 하위 지표를 포함한다."""

    __tablename__ = "fear_greed_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    sub_indicators: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_fear_greed_history_date", "date"),
        Index("idx_fear_greed_history_created_at", "created_at"),
    )


class PredictionMarket(Base):
    """예측 시장 데이터를 저장한다. Polymarket, Kalshi 등의 확률과 거래량을 추적한다."""

    __tablename__ = "prediction_markets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    market_title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(30))
    yes_probability: Mapped[float | None] = mapped_column(Numeric(5, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_prediction_markets_source", "source"),
        Index("idx_prediction_markets_category", "category"),
        Index("idx_prediction_markets_snapshot_at", "snapshot_at"),
    )


class HistoricalAnalysis(Base):
    """과거 분석 결과 모델.

    주간 단위로 분석된 기업/섹터 타임라인 데이터를 저장한다.
    """

    __tablename__ = "historical_analyses"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    sector: Mapped[str | None] = mapped_column(String(50), index=True)
    ticker: Mapped[str | None] = mapped_column(String(20), index=True)

    # 분석 내용
    timeline_events: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    company_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    market_context: Mapped[str | None] = mapped_column(Text)
    key_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    analyst_notes: Mapped[str | None] = mapped_column(Text)

    # 메타
    analysis_quality: Mapped[float | None] = mapped_column(Float)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_hist_week_sector", "week_start", "sector"),
        Index("ix_hist_week_ticker", "week_start", "ticker"),
    )


class HistoricalAnalysisProgress(Base):
    """과거 분석 진행 상태를 추적한다."""

    __tablename__ = "historical_analysis_progress"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    last_completed_week: Mapped[date] = mapped_column(Date, nullable=False)
    total_weeks_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    mode: Mapped[str] = mapped_column(String(20), default="historical")
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
