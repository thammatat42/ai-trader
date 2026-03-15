-- ==========================================
-- INITIAL DATABASE SCHEMA
-- ==========================================

-- ตาราง Log ผลวิเคราะห์ AI (ถ้ายังไม่มี)
CREATE TABLE IF NOT EXISTS ai_analysis_log (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20)   NOT NULL,
    bid             NUMERIC(12,5),
    ask             NUMERIC(12,5),
    ai_recommendation TEXT,
    lot_size        NUMERIC(6,2),
    trade_action    VARCHAR(10)   DEFAULT 'WAIT',   -- BUY / SELL / WAIT
    sl_price        NUMERIC(12,5),                   -- Stop Loss ราคาจริง
    tp_price        NUMERIC(12,5),                   -- Take Profit ราคาจริง
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ==========================================
-- ตาราง trades – บันทึกคำสั่งเทรดจริง + ผลกำไร/ขาดทุน
-- ==========================================
CREATE TABLE IF NOT EXISTS trades (
    id              SERIAL PRIMARY KEY,
    order_id        BIGINT UNIQUE,                   -- MT5 order ticket
    symbol          VARCHAR(20)   NOT NULL,
    action          VARCHAR(10)   NOT NULL,           -- BUY / SELL
    lot             NUMERIC(6,2)  NOT NULL,
    open_price      NUMERIC(12,5),
    close_price     NUMERIC(12,5),
    sl_price        NUMERIC(12,5),
    tp_price        NUMERIC(12,5),
    profit          NUMERIC(12,2),                   -- USD profit/loss
    status          VARCHAR(20)   DEFAULT 'OPEN',    -- OPEN / CLOSED
    opened_at       TIMESTAMP     DEFAULT NOW(),
    closed_at       TIMESTAMP
);

-- ==========================================
-- ตาราง bot_settings – ใช้ควบคุม Bot จาก Dashboard
-- ==========================================
CREATE TABLE IF NOT EXISTS bot_settings (
    id                  SERIAL PRIMARY KEY,
    is_running          BOOLEAN   NOT NULL DEFAULT TRUE,
    interval_seconds    INTEGER   NOT NULL DEFAULT 300,
    max_trades_per_day  INTEGER   NOT NULL DEFAULT 10,
    pause_max_retries   INTEGER   NOT NULL DEFAULT 5,     -- จำนวนครั้ง retry ขณะ BREAKPOINT (0 = retry ไม่จำกัด)
    pause_retry_sec     INTEGER   NOT NULL DEFAULT 10,    -- เวลา (วินาที) ระหว่าง retry ขณะ BREAKPOINT
    updated_at          TIMESTAMP DEFAULT NOW()
);

INSERT INTO bot_settings (is_running, interval_seconds, max_trades_per_day, pause_max_retries, pause_retry_sec)
SELECT TRUE, 300, 10, 5, 10
WHERE NOT EXISTS (SELECT 1 FROM bot_settings);

-- ==========================================
-- ตาราง bot_events – บันทึกเหตุการณ์สำคัญ
-- ==========================================
CREATE TABLE IF NOT EXISTS bot_events (
    id          SERIAL PRIMARY KEY,
    event_type  VARCHAR(50)  NOT NULL,
    message     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ==========================================
-- INDEX
-- ==========================================
CREATE INDEX IF NOT EXISTS idx_log_created    ON ai_analysis_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_created ON bot_events      (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status  ON trades          (status);
CREATE INDEX IF NOT EXISTS idx_trades_opened  ON trades          (opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_order   ON trades          (order_id);

-- ==========================================
-- ตาราง api_usage_log – บันทึกการใช้งาน AI API (OpenRouter / NVIDIA)
-- ==========================================
CREATE TABLE IF NOT EXISTS api_usage_log (
    id                  SERIAL PRIMARY KEY,
    provider            VARCHAR(20)   NOT NULL,        -- openrouter / nvidia
    model               VARCHAR(100)  NOT NULL,
    prompt_tokens       INTEGER       DEFAULT 0,
    completion_tokens   INTEGER       DEFAULT 0,
    total_tokens        INTEGER       DEFAULT 0,
    response_time_ms    INTEGER       DEFAULT 0,        -- latency in ms
    status              VARCHAR(10)   DEFAULT 'OK',     -- OK / ERROR
    created_at          TIMESTAMP     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_created  ON api_usage_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage_log (provider);
