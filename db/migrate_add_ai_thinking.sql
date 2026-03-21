-- ==========================================
-- MIGRATION: Move AI Thinking Mode from bot_settings to ai_model_config
-- + Add data_cleaned_at to bot_settings for sync filtering
-- ==========================================

-- Remove old global toggle from bot_settings (no longer used)
ALTER TABLE bot_settings DROP COLUMN IF EXISTS ai_thinking;

-- Add per-model thinking toggle to ai_model_config
ALTER TABLE ai_model_config ADD COLUMN IF NOT EXISTS ai_thinking BOOLEAN NOT NULL DEFAULT FALSE;

-- Add data cleanup timestamp (prevents MT5 sync from re-importing old trades)
ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS data_cleaned_at TIMESTAMP;
