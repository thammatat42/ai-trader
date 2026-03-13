-- ==========================================
-- MIGRATION: เพิ่มตาราง bot_settings, bot_events, trades และ column ใหม่
-- ==========================================
-- ใช้สำหรับ Database ที่มีอยู่แล้ว (มี ai_analysis_log อยู่ก่อน)
-- รันครั้งเดียวด้วยคำสั่ง:
--   docker exec -i <db_container> psql -U admin -d trading_log < db/migrate_add_bot_tables.sql
-- ==========================================

-- เพิ่ม column ใหม่ใน ai_analysis_log (ถ้ายังไม่มี)
ALTER TABLE ai_analysis_log ADD COLUMN IF NOT EXISTS trade_action VARCHAR(10) DEFAULT 'WAIT';
ALTER TABLE ai_analysis_log ADD COLUMN IF NOT EXISTS sl_price NUMERIC(12,5);
ALTER TABLE ai_analysis_log ADD COLUMN IF NOT EXISTS tp_price NUMERIC(12,5);

-- ตาราง bot_settings
CREATE TABLE IF NOT EXISTS bot_settings (
    id                  SERIAL PRIMARY KEY,
    is_running          BOOLEAN   NOT NULL DEFAULT TRUE,
    interval_seconds    INTEGER   NOT NULL DEFAULT 300,
    max_trades_per_day  INTEGER   NOT NULL DEFAULT 10,
    updated_at          TIMESTAMP DEFAULT NOW()
);

INSERT INTO bot_settings (is_running, interval_seconds, max_trades_per_day)
SELECT TRUE, 300, 10
WHERE NOT EXISTS (SELECT 1 FROM bot_settings);

-- ตาราง bot_events
CREATE TABLE IF NOT EXISTS bot_events (
    id          SERIAL PRIMARY KEY,
    event_type  VARCHAR(50)  NOT NULL,
    message     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ตาราง trades – บันทึกคำสั่งเทรดจริง + ผลกำไร/ขาดทุน
CREATE TABLE IF NOT EXISTS trades (
    id              SERIAL PRIMARY KEY,
    order_id        BIGINT UNIQUE,
    symbol          VARCHAR(20)   NOT NULL,
    action          VARCHAR(10)   NOT NULL,
    lot             NUMERIC(6,2)  NOT NULL,
    open_price      NUMERIC(12,5),
    close_price     NUMERIC(12,5),
    sl_price        NUMERIC(12,5),
    tp_price        NUMERIC(12,5),
    profit          NUMERIC(12,2),
    status          VARCHAR(20)   DEFAULT 'OPEN',
    opened_at       TIMESTAMP     DEFAULT NOW(),
    closed_at       TIMESTAMP
);

-- Index
CREATE INDEX IF NOT EXISTS idx_log_created    ON ai_analysis_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_created ON bot_events      (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status  ON trades          (status);
CREATE INDEX IF NOT EXISTS idx_trades_opened  ON trades          (opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_order   ON trades          (order_id);

-- เสร็จ!
SELECT 'Migration completed successfully ✅' AS status;
