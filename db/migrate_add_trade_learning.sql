-- ==========================================
-- MIGRATION: Add Trade Learning & Self-Improvement Tables
-- v1.0.4 — RAG context, post-trade analysis, confidence calibration
-- ==========================================

-- 1. Add AI confidence + regime columns to trades table for calibration tracking
ALTER TABLE trades ADD COLUMN IF NOT EXISTS ai_confidence INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS ai_sentiment VARCHAR(10);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS market_regime VARCHAR(20);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trend_direction VARCHAR(10);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trend_strength INTEGER;

-- 2. Post-trade analysis (AI reviews each closed trade for lessons)
CREATE TABLE IF NOT EXISTS trade_analysis (
    id              SERIAL PRIMARY KEY,
    trade_id        INTEGER REFERENCES trades(id),
    order_id        BIGINT,
    outcome         VARCHAR(10) NOT NULL,           -- WIN / LOSS
    profit          NUMERIC(12,2),
    analysis_json   JSONB,                          -- AI analysis result
    -- Extracted fields for fast queries:
    correct_signals TEXT[],                          -- e.g. {'EMA_trend', 'RSI'}
    wrong_signals   TEXT[],                          -- e.g. {'MACD', 'BB'}
    key_factor      TEXT,
    lesson          TEXT,
    confidence_justified BOOLEAN,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_analysis_order ON trade_analysis (order_id);
CREATE INDEX IF NOT EXISTS idx_trade_analysis_outcome ON trade_analysis (outcome);

-- 3. Daily performance tracking (for daily circuit breaker + regime performance)
CREATE TABLE IF NOT EXISTS daily_performance (
    id              SERIAL PRIMARY KEY,
    trade_date      DATE NOT NULL UNIQUE,
    total_trades    INTEGER DEFAULT 0,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    total_profit    NUMERIC(12,2) DEFAULT 0,
    buy_count       INTEGER DEFAULT 0,
    sell_count      INTEGER DEFAULT 0,
    avg_hold_sec    INTEGER DEFAULT 0,
    avg_win         NUMERIC(12,2) DEFAULT 0,
    avg_loss        NUMERIC(12,2) DEFAULT 0,
    max_consec_loss INTEGER DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_perf_date ON daily_performance (trade_date DESC);

-- 4. Confidence calibration tracking
CREATE TABLE IF NOT EXISTS confidence_calibration (
    id              SERIAL PRIMARY KEY,
    confidence_level INTEGER NOT NULL,              -- 1-10
    total_trades    INTEGER DEFAULT 0,
    wins            INTEGER DEFAULT 0,
    actual_win_rate NUMERIC(5,2) DEFAULT 0,
    avg_profit      NUMERIC(12,2) DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(confidence_level)
);

-- Seed confidence levels 1-10
INSERT INTO confidence_calibration (confidence_level, total_trades, wins, actual_win_rate)
SELECT g, 0, 0, 0 FROM generate_series(1, 10) g
ON CONFLICT (confidence_level) DO NOTHING;

-- 5. Signal reliability tracking (which indicators were correct/wrong)
CREATE TABLE IF NOT EXISTS signal_reliability (
    id              SERIAL PRIMARY KEY,
    signal_name     VARCHAR(50) NOT NULL UNIQUE,    -- EMA_trend, RSI, MACD, BB, SR, candle_pattern
    times_correct   INTEGER DEFAULT 0,
    times_wrong     INTEGER DEFAULT 0,
    reliability_pct NUMERIC(5,2) DEFAULT 50,
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Seed initial signals
INSERT INTO signal_reliability (signal_name) VALUES
    ('EMA_trend'), ('RSI'), ('MACD'), ('Bollinger_Bands'),
    ('Support_Resistance'), ('Candle_Pattern'), ('ATR_momentum'),
    ('Trend_Alignment'), ('Order_Book'), ('News_Macro')
ON CONFLICT (signal_name) DO NOTHING;
