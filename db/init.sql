-- AI Auto-Trading System V2 - Database Initialization
-- PostgreSQL 17 + pgvector

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- RAG Documents Table
-- Stores embeddings and content for retrieval-augmented generation
-- ============================================================
CREATE TABLE rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type VARCHAR(50) NOT NULL,
    ticker VARCHAR(10),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    source VARCHAR(50),
    relevance_score FLOAT DEFAULT 1.0
);

CREATE INDEX idx_rag_documents_embedding ON rag_documents USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_rag_documents_doc_type ON rag_documents (doc_type);
CREATE INDEX idx_rag_documents_ticker ON rag_documents (ticker);
CREATE INDEX idx_rag_documents_created_at ON rag_documents (created_at);

-- ============================================================
-- ETF Universe Table
-- Manages the set of tradeable ETFs
-- ============================================================
CREATE TABLE etf_universe (
    ticker VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    leverage FLOAT NOT NULL DEFAULT 2.0,
    underlying VARCHAR(100),
    expense_ratio FLOAT,
    avg_daily_volume INTEGER,
    enabled BOOLEAN DEFAULT FALSE,
    min_volume_threshold INTEGER DEFAULT 100000,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    added_by VARCHAR(20) DEFAULT 'system',
    notes TEXT
);

-- ============================================================
-- Trades Table
-- Records all trade entries and exits
-- ============================================================
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT,
    entry_at TIMESTAMPTZ NOT NULL,
    exit_at TIMESTAMPTZ,
    pnl_pct FLOAT,
    pnl_amount FLOAT,
    hold_minutes INTEGER,
    exit_reason VARCHAR(50),
    ai_confidence FLOAT,
    ai_signals JSONB DEFAULT '[]',
    market_regime VARCHAR(20),
    post_analysis JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_ticker ON trades (ticker);
CREATE INDEX idx_trades_entry_at ON trades (entry_at);
CREATE INDEX idx_trades_exit_reason ON trades (exit_reason);
CREATE INDEX idx_trades_created_at ON trades (created_at);

-- ============================================================
-- Indicator History Table
-- Stores time-series technical indicator data
-- ============================================================
CREATE TABLE indicator_history (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    indicator_name VARCHAR(50) NOT NULL,
    value FLOAT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_indicator_history_composite ON indicator_history (ticker, indicator_name, recorded_at);

-- ============================================================
-- Strategy Parameter History Table
-- Tracks changes to strategy parameters over time
-- ============================================================
CREATE TABLE strategy_param_history (
    id BIGSERIAL PRIMARY KEY,
    param_name VARCHAR(50) NOT NULL,
    old_value FLOAT,
    new_value FLOAT NOT NULL,
    change_reason TEXT,
    approved_by VARCHAR(20),
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_strategy_param_history_param ON strategy_param_history (param_name);
CREATE INDEX idx_strategy_param_history_applied ON strategy_param_history (applied_at);

-- ============================================================
-- Feedback Reports Table
-- Daily/weekly performance feedback and analysis
-- ============================================================
CREATE TABLE feedback_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type VARCHAR(20) NOT NULL,
    report_date DATE NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_feedback_reports_type_date ON feedback_reports (report_type, report_date);

-- ============================================================
-- Crawl Checkpoints Table
-- Tracks crawling progress for resumability
-- ============================================================
CREATE TABLE crawl_checkpoints (
    id SERIAL PRIMARY KEY,
    checkpoint_at TIMESTAMPTZ NOT NULL,
    total_articles INTEGER,
    source_stats JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Articles Table
-- Stores crawled news articles
-- ============================================================
CREATE TABLE articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(50) NOT NULL,
    headline TEXT NOT NULL,
    content TEXT,
    url TEXT,
    published_at TIMESTAMPTZ,
    language VARCHAR(5) DEFAULT 'en',
    tickers_mentioned JSONB DEFAULT '[]',
    sentiment_score FLOAT,
    classification JSONB DEFAULT '{}',
    is_processed BOOLEAN DEFAULT FALSE,
    crawled_at TIMESTAMPTZ DEFAULT NOW(),
    content_hash VARCHAR(64) UNIQUE
);

CREATE INDEX idx_articles_source_crawled ON articles (source, crawled_at);
CREATE INDEX idx_articles_is_processed ON articles (is_processed);
CREATE INDEX idx_articles_content_hash ON articles (content_hash);
CREATE INDEX idx_articles_published_at ON articles (published_at);

-- ============================================================
-- Pending Adjustments Table
-- Parameter change proposals awaiting approval
-- ============================================================
CREATE TABLE pending_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    param_name VARCHAR(50) NOT NULL,
    current_value FLOAT NOT NULL,
    proposed_value FLOAT NOT NULL,
    change_pct FLOAT NOT NULL,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_pending_adjustments_status ON pending_adjustments (status);
CREATE INDEX idx_pending_adjustments_created ON pending_adjustments (created_at);

-- ============================================================
-- Seed Data: ETF Universe
-- ============================================================
INSERT INTO etf_universe (ticker, name, direction, leverage, underlying, expense_ratio, avg_daily_volume, enabled, min_volume_threshold, notes) VALUES
    ('TQQQ', 'ProShares UltraPro QQQ', 'bull', 3.0, 'NASDAQ-100', 0.88, 80000000, TRUE, 100000, '3x leveraged NASDAQ-100 bull'),
    ('SQQQ', 'ProShares UltraPro Short QQQ', 'bear', 3.0, 'NASDAQ-100', 0.95, 50000000, TRUE, 100000, '3x leveraged NASDAQ-100 bear'),
    ('UPRO', 'ProShares UltraPro S&P500', 'bull', 3.0, 'S&P 500', 0.91, 10000000, TRUE, 100000, '3x leveraged S&P500 bull'),
    ('SPXU', 'ProShares UltraPro Short S&P500', 'bear', 3.0, 'S&P 500', 0.91, 8000000, TRUE, 100000, '3x leveraged S&P500 bear'),
    ('SOXL', 'Direxion Daily Semiconductor Bull 3X', 'bull', 3.0, 'ICE Semiconductor', 0.76, 40000000, TRUE, 100000, '3x leveraged semiconductor bull'),
    ('SOXS', 'Direxion Daily Semiconductor Bear 3X', 'bear', 3.0, 'ICE Semiconductor', 1.01, 20000000, TRUE, 100000, '3x leveraged semiconductor bear'),
    ('TECL', 'Direxion Daily Technology Bull 3X', 'bull', 3.0, 'Technology Select', 0.94, 5000000, TRUE, 100000, '3x leveraged technology bull'),
    ('TECS', 'Direxion Daily Technology Bear 3X', 'bear', 3.0, 'Technology Select', 1.08, 3000000, TRUE, 100000, '3x leveraged technology bear'),
    ('TNA', 'Direxion Daily Small Cap Bull 3X', 'bull', 3.0, 'Russell 2000', 0.95, 8000000, FALSE, 100000, '3x leveraged Russell 2000 bull'),
    ('TZA', 'Direxion Daily Small Cap Bear 3X', 'bear', 3.0, 'Russell 2000', 1.01, 5000000, FALSE, 100000, '3x leveraged Russell 2000 bear'),
    ('FNGU', 'MicroSectors FANG+ Bull 3X', 'bull', 3.0, 'FANG+', 0.95, 3000000, FALSE, 100000, '3x leveraged FANG+ bull'),
    ('FNGD', 'MicroSectors FANG+ Bear 3X', 'bear', 3.0, 'FANG+', 0.95, 2000000, FALSE, 100000, '3x leveraged FANG+ bear'),
    ('UVXY', 'ProShares Ultra VIX Short-Term', 'bull', 1.5, 'VIX Short-Term Futures', 0.95, 20000000, FALSE, 100000, '1.5x leveraged VIX futures'),
    ('SVXY', 'ProShares Short VIX Short-Term', 'bear', 0.5, 'VIX Short-Term Futures', 0.95, 5000000, FALSE, 100000, '0.5x inverse VIX futures');

-- ============================================================
-- Tax Records Table
-- Tracks realized gains/losses and tax calculations per trade
-- ============================================================
CREATE TABLE tax_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    realized_gain_usd FLOAT NOT NULL DEFAULT 0.0,
    realized_loss_usd FLOAT NOT NULL DEFAULT 0.0,
    fx_rate_at_trade FLOAT NOT NULL,
    realized_gain_krw FLOAT NOT NULL DEFAULT 0.0,
    realized_loss_krw FLOAT NOT NULL DEFAULT 0.0,
    tax_category VARCHAR(30) NOT NULL DEFAULT '양도소득세',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tax_records_trade_id ON tax_records (trade_id);
CREATE INDEX idx_tax_records_year ON tax_records (year);
CREATE INDEX idx_tax_records_created_at ON tax_records (created_at);

-- ============================================================
-- FX Rates Table
-- Historical USD/KRW exchange rate snapshots
-- ============================================================
CREATE TABLE fx_rates (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    usd_krw_rate FLOAT NOT NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'KIS',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fx_rates_timestamp ON fx_rates (timestamp);
CREATE INDEX idx_fx_rates_source ON fx_rates (source);

-- ============================================================
-- Slippage Log Table
-- Records expected vs actual fill prices for slippage analysis
-- ============================================================
CREATE TABLE slippage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    expected_price FLOAT NOT NULL,
    actual_price FLOAT NOT NULL,
    slippage_pct FLOAT NOT NULL,
    volume_at_fill INTEGER,
    time_of_day TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_slippage_log_trade_id ON slippage_log (trade_id);
CREATE INDEX idx_slippage_log_ticker ON slippage_log (ticker);
CREATE INDEX idx_slippage_log_created_at ON slippage_log (created_at);

-- ============================================================
-- Emergency Events Table
-- Logs emergency protocol activations and resolutions
-- ============================================================
CREATE TABLE emergency_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(30) NOT NULL,
    trigger_value FLOAT,
    action_taken TEXT NOT NULL,
    positions_affected JSONB DEFAULT '[]',
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_emergency_events_event_type ON emergency_events (event_type);
CREATE INDEX idx_emergency_events_created_at ON emergency_events (created_at);

-- ============================================================
-- Benchmark Snapshots Table
-- Periodic comparison of AI strategy vs passive benchmarks
-- ============================================================
CREATE TABLE benchmark_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    period_type VARCHAR(10) NOT NULL DEFAULT 'daily',
    ai_return_pct FLOAT NOT NULL,
    spy_buyhold_return_pct FLOAT NOT NULL,
    sso_buyhold_return_pct FLOAT NOT NULL,
    cash_return_pct FLOAT NOT NULL DEFAULT 0.0,
    ai_vs_spy_diff FLOAT NOT NULL,
    ai_vs_sso_diff FLOAT NOT NULL,
    consecutive_underperform_weeks INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_benchmark_snapshots_date ON benchmark_snapshots (date);
CREATE INDEX idx_benchmark_snapshots_period_type ON benchmark_snapshots (period_type);
CREATE INDEX idx_benchmark_snapshots_created_at ON benchmark_snapshots (created_at);

-- ============================================================
-- Capital Guard Log Table
-- Logs safety checks for capital validation (3-set, balance, order)
-- ============================================================
CREATE TABLE capital_guard_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_type VARCHAR(30) NOT NULL,
    passed BOOLEAN NOT NULL,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_capital_guard_log_check_type ON capital_guard_log (check_type);
CREATE INDEX idx_capital_guard_log_passed ON capital_guard_log (passed);
CREATE INDEX idx_capital_guard_log_created_at ON capital_guard_log (created_at);

-- ============================================================
-- Notification Log Table
-- Records all outgoing notifications across channels
-- ============================================================
CREATE TABLE notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel VARCHAR(20) NOT NULL,
    severity VARCHAR(10) NOT NULL DEFAULT 'info',
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notification_log_channel ON notification_log (channel);
CREATE INDEX idx_notification_log_severity ON notification_log (severity);
CREATE INDEX idx_notification_log_sent_at ON notification_log (sent_at);
CREATE INDEX idx_notification_log_created_at ON notification_log (created_at);

-- ============================================================
-- Profit Targets Table
-- 월별 수익 목표 및 실현/미실현 손익 추적
-- ============================================================
CREATE TABLE profit_targets (
    id BIGSERIAL PRIMARY KEY,
    month DATE NOT NULL,
    target_usd DECIMAL(10,2) NOT NULL DEFAULT 300.00,
    realized_pnl DECIMAL(10,2) DEFAULT 0,
    unrealized_pnl DECIMAL(10,2) DEFAULT 0,
    aggression_override VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_profit_targets_month ON profit_targets (month);

-- ============================================================
-- Daily PnL Log Table
-- 일별 손익 기록 (실현/미실현 PnL, 거래 횟수, 공격성 수준)
-- ============================================================
CREATE TABLE daily_pnl_log (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    realized_pnl DECIMAL(10,2) NOT NULL,
    unrealized_pnl DECIMAL(10,2),
    trade_count INTEGER DEFAULT 0,
    aggression_level VARCHAR(20),
    target_daily DECIMAL(10,2)
);

CREATE INDEX idx_daily_pnl_log_date ON daily_pnl_log (date);

-- ============================================================
-- Risk Config Table
-- 리스크 관리 파라미터 (key-value)
-- ============================================================
CREATE TABLE risk_config (
    id BIGSERIAL PRIMARY KEY,
    param_key VARCHAR(50) UNIQUE NOT NULL,
    param_value DECIMAL(10,4) NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_risk_config_param_key ON risk_config (param_key);

-- Seed Data: Risk Config
INSERT INTO risk_config (param_key, param_value, description) VALUES
    ('daily_loss_limit_pct', -0.02, '일일 최대 손실 한도 (%)'),
    ('monthly_loss_limit_pct', -0.05, '월간 최대 손실 한도 (%)'),
    ('single_position_max_pct', 0.30, '단일 포지션 최대 비중 (%)'),
    ('total_invested_max_pct', 0.60, '총 투자 비중 최대 한도 (%)'),
    ('stop_loss_pct', -0.05, '손절 기준 (%)'),
    ('trailing_stop_pct', -0.03, '트레일링 스탑 기준 (%)'),
    ('var_max_pct', 0.03, 'VaR 최대 한도 (%)'),
    ('max_concurrent_positions', 3, '최대 동시 보유 포지션 수');

-- ============================================================
-- Risk Events Table
-- 리스크 이벤트 기록 (게이트 트리거, 손절, 쿨다운 등)
-- ============================================================
CREATE TABLE risk_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(30) NOT NULL,
    gate_name VARCHAR(30),
    severity VARCHAR(10),
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_risk_events_event_type ON risk_events (event_type);
CREATE INDEX idx_risk_events_severity ON risk_events (severity);
CREATE INDEX idx_risk_events_created_at ON risk_events (created_at);

-- ============================================================
-- Backtest Results Table
-- 백테스트 실행 결과 (수익률, 드로다운, 샤프비율 등)
-- ============================================================
CREATE TABLE backtest_results (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    params JSONB NOT NULL,
    total_return DECIMAL(8,4),
    max_drawdown DECIMAL(8,4),
    sharpe_ratio DECIMAL(6,3),
    win_rate DECIMAL(5,3),
    profit_factor DECIMAL(6,3),
    recommendation TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_backtest_results_run_date ON backtest_results (run_date);
CREATE INDEX idx_backtest_results_created_at ON backtest_results (created_at);

-- ============================================================
-- Fear & Greed History Table
-- Fear & Greed 지수 이력 (7개 하위 지표 포함)
-- ============================================================
CREATE TABLE fear_greed_history (
    id BIGSERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    score INTEGER NOT NULL,
    rating VARCHAR(20) NOT NULL,
    sub_indicators JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fear_greed_history_date ON fear_greed_history (date);
CREATE INDEX idx_fear_greed_history_created_at ON fear_greed_history (created_at);

-- ============================================================
-- Prediction Markets Table
-- 예측 시장 데이터 (Polymarket, Kalshi 확률 및 거래량)
-- ============================================================
CREATE TABLE prediction_markets (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL,
    market_title TEXT NOT NULL,
    category VARCHAR(30),
    yes_probability DECIMAL(5,4),
    volume BIGINT,
    snapshot_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prediction_markets_source ON prediction_markets (source);
CREATE INDEX idx_prediction_markets_category ON prediction_markets (category);
CREATE INDEX idx_prediction_markets_snapshot_at ON prediction_markets (snapshot_at);

-- ============================================================
-- Historical Analyses Table
-- 과거분석팀 주간 분석 결과 (기업/섹터 타임라인)
-- ============================================================
CREATE TABLE historical_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    sector VARCHAR(50),
    ticker VARCHAR(20),
    timeline_events JSONB NOT NULL,
    company_info JSONB,
    market_context TEXT,
    key_metrics JSONB,
    analyst_notes TEXT,
    analysis_quality FLOAT,
    source_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ix_hist_week_start ON historical_analyses (week_start);
CREATE INDEX ix_hist_sector ON historical_analyses (sector);
CREATE INDEX ix_hist_ticker ON historical_analyses (ticker);
CREATE INDEX ix_hist_week_sector ON historical_analyses (week_start, sector);
CREATE INDEX ix_hist_week_ticker ON historical_analyses (week_start, ticker);

-- ============================================================
-- Historical Analysis Progress Table
-- 과거분석 진행 상태 추적
-- ============================================================
CREATE TABLE historical_analysis_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    last_completed_week DATE NOT NULL,
    total_weeks_analyzed INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running',
    mode VARCHAR(20) DEFAULT 'historical',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
