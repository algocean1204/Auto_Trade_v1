"""V2 순수 초기 스키마 -- 26개 테이블 신규 생성이다.

V1 호환성 없이 완전히 새로운 스키마로 시작한다.
ALTER TABLE, DROP COLUMN 등 V1 잔재가 전혀 없다.

Revision ID: 0001_v2_clean
Revises: (없음 -- 최초 마이그레이션이다)
Create Date: 2026-02-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ── 리비전 식별자 ──
revision: str = "0001_v2_clean"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """26개 V2 테이블을 순서대로 생성한다.

    모든 PK는 String(UUID) 타입, 모든 타임스탬프는 timezone=True이다.
    외래 키 없이 독립 테이블로 설계하여 삭제 순서 제약이 없다.
    """

    # ── 1. 수집된 기사 ──────────────────────────────────────────────────────
    op.create_table(
        "articles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_articles_url"),
    )
    # url 고유 인덱스 (중복 수집 방지)
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"], unique=False)
    op.create_index("ix_articles_published_at", "articles", ["published_at"], unique=False)

    # ── 2. 매매 기록 ────────────────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 티커별 매매 이력 조회 및 날짜 범위 필터링에 사용한다
    op.create_index("ix_trades_ticker", "trades", ["ticker"], unique=False)
    op.create_index("ix_trades_created_at", "trades", ["created_at"], unique=False)

    # ── 3. ETF 유니버스 ────────────────────────────────────────────────────
    op.create_table(
        "etf_universe",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("leverage", sa.Float(), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", name="uq_etf_universe_ticker"),
    )

    # ── 4. 지표 이력 ────────────────────────────────────────────────────────
    op.create_table(
        "indicator_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("indicator_name", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 특정 티커+지표 이름 조합으로 최근값 조회에 사용한다
    op.create_index("ix_indicator_history_ticker", "indicator_history", ["ticker"], unique=False)
    op.create_index(
        "ix_indicator_history_ticker_name",
        "indicator_history",
        ["ticker", "indicator_name"],
        unique=False,
    )

    # ── 5. 전략 파라미터 변경 이력 ─────────────────────────────────────────
    op.create_table(
        "strategy_param_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("param_name", sa.String(), nullable=False),
        sa.Column("old_value", sa.String(), nullable=True),
        sa.Column("new_value", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_strategy_param_history_param_name",
        "strategy_param_history",
        ["param_name"],
        unique=False,
    )

    # ── 6. 피드백 보고서 ───────────────────────────────────────────────────
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_type", sa.String(), nullable=True),
        sa.Column("content", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_reports_report_type",
        "feedback_reports",
        ["report_type"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_reports_created_at",
        "feedback_reports",
        ["created_at"],
        unique=False,
    )

    # ── 7. 크롤링 체크포인트 ────────────────────────────────────────────────
    op.create_table(
        "crawl_checkpoints",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("last_url", sa.String(), nullable=True),
        sa.Column("last_published", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", name="uq_crawl_checkpoints_source"),
    )

    # ── 8. 대기 중 조정 ─────────────────────────────────────────────────────
    op.create_table(
        "pending_adjustments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("adjustment_type", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 미적용 조정 항목 필터링에 사용한다
    op.create_index(
        "ix_pending_adjustments_ticker_applied",
        "pending_adjustments",
        ["ticker", "applied"],
        unique=False,
    )

    # ── 9. 세금 기록 ────────────────────────────────────────────────────────
    op.create_table(
        "tax_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("gain_usd", sa.Float(), nullable=True),
        sa.Column("tax_krw", sa.Float(), nullable=True),
        sa.Column("fx_rate", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tax_records_ticker", "tax_records", ["ticker"], unique=False)
    op.create_index("ix_tax_records_created_at", "tax_records", ["created_at"], unique=False)

    # ── 10. 환율 기록 ───────────────────────────────────────────────────────
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("usd_krw", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 최신 환율 조회를 위한 시간 역순 인덱스이다
    op.create_index("ix_fx_rates_created_at", "fx_rates", ["created_at"], unique=False)

    # ── 11. 슬리피지 기록 ──────────────────────────────────────────────────
    op.create_table(
        "slippage_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=True),
        sa.Column("slippage_pct", sa.Float(), nullable=True),
        sa.Column("slippage_amount", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 12. 긴급 이벤트 ────────────────────────────────────────────────────
    op.create_table(
        "emergency_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("action_taken", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_emergency_events_event_type",
        "emergency_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_emergency_events_created_at",
        "emergency_events",
        ["created_at"],
        unique=False,
    )

    # ── 13. 벤치마크 스냅샷 ────────────────────────────────────────────────
    op.create_table(
        "benchmark_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("benchmark", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("portfolio_value", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_benchmark_snapshots_benchmark",
        "benchmark_snapshots",
        ["benchmark"],
        unique=False,
    )

    # ── 14. 자본 보호 로그 ─────────────────────────────────────────────────
    op.create_table(
        "capital_guard_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("guard_type", sa.String(), nullable=False),
        sa.Column("trigger_value", sa.Float(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_capital_guard_log_guard_type",
        "capital_guard_log",
        ["guard_type"],
        unique=False,
    )

    # ── 15. 알림 로그 ──────────────────────────────────────────────────────
    op.create_table(
        "notification_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_log_event_type",
        "notification_log",
        ["event_type"],
        unique=False,
    )

    # ── 16. 수익 목표 ──────────────────────────────────────────────────────
    op.create_table(
        "profit_targets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("target_pct", sa.Float(), nullable=False),
        sa.Column("achieved", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profit_targets_ticker_achieved",
        "profit_targets",
        ["ticker", "achieved"],
        unique=False,
    )

    # ── 17. 일일 PnL ───────────────────────────────────────────────────────
    op.create_table(
        "daily_pnl_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("pnl_amount", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("equity", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 날짜 문자열(YYYY-MM-DD)로 당일 PnL 조회에 사용한다
    op.create_index("ix_daily_pnl_log_date", "daily_pnl_log", ["date"], unique=False)

    # ── 18. 리스크 설정 ────────────────────────────────────────────────────
    op.create_table(
        "risk_config",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("param_name", sa.String(), nullable=False),
        sa.Column("param_value", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("param_name", name="uq_risk_config_param_name"),
    )

    # ── 19. 리스크 이벤트 ─────────────────────────────────────────────────
    op.create_table(
        "risk_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_events_event_type", "risk_events", ["event_type"], unique=False)
    op.create_index("ix_risk_events_severity", "risk_events", ["severity"], unique=False)
    op.create_index("ix_risk_events_created_at", "risk_events", ["created_at"], unique=False)

    # ── 20. 백테스트 결과 ─────────────────────────────────────────────────
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("params", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_backtest_results_strategy_name",
        "backtest_results",
        ["strategy_name"],
        unique=False,
    )

    # ── 21. Fear&Greed 이력 ────────────────────────────────────────────────
    op.create_table(
        "fear_greed_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("index_value", sa.Float(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fear_greed_history_created_at",
        "fear_greed_history",
        ["created_at"],
        unique=False,
    )

    # ── 22. 예측시장 ───────────────────────────────────────────────────────
    op.create_table(
        "prediction_markets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("market_name", sa.String(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prediction_markets_market_name",
        "prediction_markets",
        ["market_name"],
        unique=False,
    )

    # ── 23. 과거 분석 ──────────────────────────────────────────────────────
    op.create_table(
        "historical_analyses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("analysis_type", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("result", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_analyses_analysis_type",
        "historical_analyses",
        ["analysis_type"],
        unique=False,
    )

    # ── 24. 분석 진행 ──────────────────────────────────────────────────────
    op.create_table(
        "historical_analysis_progress",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("progress_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_analysis_progress_task_name",
        "historical_analysis_progress",
        ["task_name"],
        unique=False,
    )

    # ── 25. 틱 데이터 ──────────────────────────────────────────────────────
    op.create_table(
        "tick_data",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 틱 데이터 조회 시 티커+시간 복합 조건이 가장 빈번하게 사용된다
    op.create_index("ix_tick_data_ticker", "tick_data", ["ticker"], unique=False)
    op.create_index(
        "ix_tick_data_ticker_timestamp",
        "tick_data",
        ["ticker", "timestamp"],
        unique=False,
    )

    # ── 26. RAG 문서 ────────────────────────────────────────────────────────
    op.create_table(
        "rag_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("doc_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("embedding_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_documents_doc_type", "rag_documents", ["doc_type"], unique=False)


def downgrade() -> None:
    """26개 테이블을 생성 역순으로 모두 삭제한다.

    외래 키 의존성이 없으므로 어떤 순서로 삭제해도 무방하다.
    명확성을 위해 생성 역순(26→1)으로 삭제한다.
    """

    # ── 26 → 1 역순 삭제 ──────────────────────────────────────────────────
    op.drop_index("ix_rag_documents_doc_type", table_name="rag_documents")
    op.drop_table("rag_documents")

    op.drop_index("ix_tick_data_ticker_timestamp", table_name="tick_data")
    op.drop_index("ix_tick_data_ticker", table_name="tick_data")
    op.drop_table("tick_data")

    op.drop_index(
        "ix_historical_analysis_progress_task_name",
        table_name="historical_analysis_progress",
    )
    op.drop_table("historical_analysis_progress")

    op.drop_index(
        "ix_historical_analyses_analysis_type", table_name="historical_analyses"
    )
    op.drop_table("historical_analyses")

    op.drop_index("ix_prediction_markets_market_name", table_name="prediction_markets")
    op.drop_table("prediction_markets")

    op.drop_index("ix_fear_greed_history_created_at", table_name="fear_greed_history")
    op.drop_table("fear_greed_history")

    op.drop_index("ix_backtest_results_strategy_name", table_name="backtest_results")
    op.drop_table("backtest_results")

    op.drop_index("ix_risk_events_created_at", table_name="risk_events")
    op.drop_index("ix_risk_events_severity", table_name="risk_events")
    op.drop_index("ix_risk_events_event_type", table_name="risk_events")
    op.drop_table("risk_events")

    op.drop_table("risk_config")

    op.drop_index("ix_daily_pnl_log_date", table_name="daily_pnl_log")
    op.drop_table("daily_pnl_log")

    op.drop_index("ix_profit_targets_ticker_achieved", table_name="profit_targets")
    op.drop_table("profit_targets")

    op.drop_index("ix_notification_log_event_type", table_name="notification_log")
    op.drop_table("notification_log")

    op.drop_index("ix_capital_guard_log_guard_type", table_name="capital_guard_log")
    op.drop_table("capital_guard_log")

    op.drop_index("ix_benchmark_snapshots_benchmark", table_name="benchmark_snapshots")
    op.drop_table("benchmark_snapshots")

    op.drop_index("ix_emergency_events_created_at", table_name="emergency_events")
    op.drop_index("ix_emergency_events_event_type", table_name="emergency_events")
    op.drop_table("emergency_events")

    op.drop_table("slippage_log")

    op.drop_index("ix_fx_rates_created_at", table_name="fx_rates")
    op.drop_table("fx_rates")

    op.drop_index("ix_tax_records_created_at", table_name="tax_records")
    op.drop_index("ix_tax_records_ticker", table_name="tax_records")
    op.drop_table("tax_records")

    op.drop_index("ix_pending_adjustments_ticker_applied", table_name="pending_adjustments")
    op.drop_table("pending_adjustments")

    op.drop_table("crawl_checkpoints")

    op.drop_index("ix_feedback_reports_created_at", table_name="feedback_reports")
    op.drop_index("ix_feedback_reports_report_type", table_name="feedback_reports")
    op.drop_table("feedback_reports")

    op.drop_index(
        "ix_strategy_param_history_param_name", table_name="strategy_param_history"
    )
    op.drop_table("strategy_param_history")

    op.drop_index("ix_indicator_history_ticker_name", table_name="indicator_history")
    op.drop_index("ix_indicator_history_ticker", table_name="indicator_history")
    op.drop_table("indicator_history")

    op.drop_table("etf_universe")

    op.drop_index("ix_trades_created_at", table_name="trades")
    op.drop_index("ix_trades_ticker", table_name="trades")
    op.drop_table("trades")

    op.drop_index("ix_articles_published_at", table_name="articles")
    op.drop_index("ix_articles_content_hash", table_name="articles")
    op.drop_table("articles")
