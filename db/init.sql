-- ==========================================
-- AI Trader v2 - Database Initialization
-- ==========================================
-- Tables are managed by Alembic migrations.
-- This script only creates PostgreSQL extensions
-- needed by the application.
-- ==========================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

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
