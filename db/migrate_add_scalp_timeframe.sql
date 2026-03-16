-- ==========================================
-- MIGRATION: เพิ่ม scalp_timeframe ใน bot_settings
-- เพื่อให้สามารถเปลี่ยน Scalp Timeframe ผ่าน Dashboard ได้แบบ dynamic
-- ==========================================

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS scalp_timeframe VARCHAR(10) NOT NULL DEFAULT 'M15';
