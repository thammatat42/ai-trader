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
-- ตาราง bot_settings – ใช้ควบคุม Bot จาก Dashboard
-- ==========================================
CREATE TABLE IF NOT EXISTS bot_settings (
    id                  SERIAL PRIMARY KEY,
    is_running          BOOLEAN   NOT NULL DEFAULT TRUE,
    interval_seconds    INTEGER   NOT NULL DEFAULT 300,   -- 5 นาที (เหมาะกับ M15-H1)
    max_trades_per_day  INTEGER   NOT NULL DEFAULT 10,
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- ใส่ค่าเริ่มต้น 1 แถว (ถ้ายังไม่มี)
INSERT INTO bot_settings (is_running, interval_seconds, max_trades_per_day)
SELECT TRUE, 300, 10
WHERE NOT EXISTS (SELECT 1 FROM bot_settings);

-- ==========================================
-- ตาราง bot_events – บันทึกเหตุการณ์สำคัญ
-- ==========================================
CREATE TABLE IF NOT EXISTS bot_events (
    id          SERIAL PRIMARY KEY,
    event_type  VARCHAR(50)  NOT NULL,   -- START, STOP, ERROR, KILL_SWITCH, CONFIG_CHANGE
    message     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ==========================================
-- INDEX สำหรับ Query ที่ใช้บ่อย
-- ==========================================
CREATE INDEX IF NOT EXISTS idx_log_created   ON ai_analysis_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_created ON bot_events      (created_at DESC);
