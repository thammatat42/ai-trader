-- ==========================================
-- MIGRATION: Move AI Thinking Mode from bot_settings to ai_model_config
-- Thinking is now per-model, configured on the AI Models page
-- ==========================================

-- Remove old global toggle from bot_settings (no longer used)
ALTER TABLE bot_settings DROP COLUMN IF EXISTS ai_thinking;

-- Add per-model thinking toggle to ai_model_config
ALTER TABLE ai_model_config ADD COLUMN IF NOT EXISTS ai_thinking BOOLEAN NOT NULL DEFAULT FALSE;
