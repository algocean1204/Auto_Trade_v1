"""SQLite 초기 스키마 -- 현재 ORM 기준 27개 테이블 전체를 SQLite 호환 DDL로 정의한다.

독립적인 initial migration이다. 0001~0003은 PostgreSQL 전용(비활성)이므로
SQLite 환경에서는 이 파일만 단독으로 실행한다.
실제 시스템은 Base.metadata.create_all()로 테이블을 생성하므로,
이 파일은 문서화/감사/향후 마이그레이션 체인 유지 목적이다.

Revision ID: 0004
Revises: None (독립 initial migration)
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# ── 리비전 식별자 ──
revision: str = "0004"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """현재 ORM 모델 기준 27개 테이블을 SQLite 호환 DDL로 생성한다.

    모든 server_default는 sa.text("(datetime('now'))") 형식이다.
    JSON 컬럼은 sa.JSON()을 사용한다 (postgresql.JSON 아님).
    """

    # ── 1. 수집된 기사 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_articles_url"),
    )
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"], unique=False)

    # ── 2. 매매 기록 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_ticker", "trades", ["ticker"], unique=False)

    # ── 3. ETF 유니버스 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", name="uq_etf_universe_ticker"),
    )

    # ── 4. 지표 이력 ──
    op.create_table(
        "indicator_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("indicator_name", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_indicator_history_ticker", "indicator_history", ["ticker"], unique=False)

    # ── 5. 전략 파라미터 변경 이력 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 6. 피드백 보고서 ──
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_type", sa.String(), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 7. 크롤링 체크포인트 ──
    op.create_table(
        "crawl_checkpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_articles", sa.Integer(), nullable=True),
        sa.Column("source_stats", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 8. 대기 중 조정 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 9. 세금 기록 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 10. 환율 기록 ──
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usd_krw_rate", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 11. 슬리피지 기록 ──
    op.create_table(
        "slippage_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=True),
        sa.Column("slippage_pct", sa.Float(), nullable=True),
        sa.Column("slippage_amount", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 12. 긴급 이벤트 ──
    op.create_table(
        "emergency_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("action_taken", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 13. 벤치마크 스냅샷 ──
    op.create_table(
        "benchmark_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("benchmark", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("portfolio_value", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 14. 자본 보호 로그 ──
    op.create_table(
        "capital_guard_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("guard_type", sa.String(), nullable=False),
        sa.Column("trigger_value", sa.Float(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 15. 알림 로그 ──
    op.create_table(
        "notification_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 16. 수익 목표 ──
    op.create_table(
        "profit_targets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("target_pct", sa.Float(), nullable=False),
        sa.Column("achieved", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 17. 일일 PnL ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_pnl_log_date", "daily_pnl_log", ["date"], unique=False)

    # ── 18. 리스크 설정 ──
    op.create_table(
        "risk_config",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("param_name", sa.String(), nullable=False),
        sa.Column("param_value", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("param_name", name="uq_risk_config_param_name"),
    )

    # ── 19. 리스크 이벤트 ──
    op.create_table(
        "risk_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 20. 백테스트 결과 ──
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 21. Fear&Greed 이력 ──
    op.create_table(
        "fear_greed_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("index_value", sa.Float(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 22. 예측시장 ──
    op.create_table(
        "prediction_markets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("market_name", sa.String(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 23. 과거 분석 ──
    op.create_table(
        "historical_analyses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("analysis_type", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 24. 분석 진행 ──
    op.create_table(
        "historical_analysis_progress",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("progress_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 25. 틱 데이터 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tick_data_ticker", "tick_data", ["ticker"], unique=False)

    # ── 26. RAG 문서 ──
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
            server_default=sa.text("(datetime('now'))"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 27. 유니버스 설정 ──
    op.create_table(
        "universe_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False, server_default="AMS"),
        sa.Column("sector", sa.String(50), nullable=False, server_default="broad_market"),
        sa.Column("leverage", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("is_inverse", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("pair_ticker", sa.String(20), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", name="uq_universe_config_ticker"),
    )
    op.create_index("ix_universe_config_ticker", "universe_config", ["ticker"], unique=True)
    op.create_index("ix_universe_config_enabled", "universe_config", ["enabled"], unique=False)


def downgrade() -> None:
    """27개 테이블을 생성 역순으로 모두 삭제한다."""

    op.drop_index("ix_universe_config_enabled", table_name="universe_config")
    op.drop_index("ix_universe_config_ticker", table_name="universe_config")
    op.drop_table("universe_config")

    op.drop_table("rag_documents")

    op.drop_index("ix_tick_data_ticker", table_name="tick_data")
    op.drop_table("tick_data")

    op.drop_table("historical_analysis_progress")
    op.drop_table("historical_analyses")
    op.drop_table("prediction_markets")
    op.drop_table("fear_greed_history")
    op.drop_table("backtest_results")
    op.drop_table("risk_events")
    op.drop_table("risk_config")

    op.drop_index("ix_daily_pnl_log_date", table_name="daily_pnl_log")
    op.drop_table("daily_pnl_log")

    op.drop_table("profit_targets")
    op.drop_table("notification_log")
    op.drop_table("capital_guard_log")
    op.drop_table("benchmark_snapshots")
    op.drop_table("emergency_events")
    op.drop_table("slippage_log")
    op.drop_table("fx_rates")
    op.drop_table("tax_records")
    op.drop_table("pending_adjustments")
    op.drop_table("crawl_checkpoints")
    op.drop_table("feedback_reports")
    op.drop_table("strategy_param_history")

    op.drop_index("ix_indicator_history_ticker", table_name="indicator_history")
    op.drop_table("indicator_history")

    op.drop_table("etf_universe")

    op.drop_index("ix_trades_ticker", table_name="trades")
    op.drop_table("trades")

    op.drop_index("ix_articles_content_hash", table_name="articles")
    op.drop_table("articles")
