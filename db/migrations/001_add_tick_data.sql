-- Migration: 001_add_tick_data
-- KIS WebSocket 실시간 체결 틱 데이터 저장 테이블 추가
-- vectorbt 백테스팅 및 파라미터 최적화용 원시 데이터

BEGIN;

CREATE TABLE IF NOT EXISTS tick_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    price FLOAT NOT NULL,
    volume INTEGER NOT NULL,
    buy_volume INTEGER DEFAULT 0,
    sell_volume INTEGER DEFAULT 0,
    bid_price FLOAT,
    ask_price FLOAT,
    execution_strength FLOAT,
    local_date VARCHAR(10),
    local_time VARCHAR(10),
    kr_time VARCHAR(10),
    raw_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tick_data_ticker ON tick_data (ticker);
CREATE INDEX IF NOT EXISTS ix_tick_data_ticker_created ON tick_data (ticker, created_at);

COMMIT;
