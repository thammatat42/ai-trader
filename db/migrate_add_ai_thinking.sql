-- ==========================================
-- MIGRATION: Add AI Thinking Mode to bot_settings
-- Allows toggling thinking/reasoning mode from Dashboard
-- ==========================================
ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS ai_thinking BOOLEAN NOT NULL DEFAULT FALSE;
