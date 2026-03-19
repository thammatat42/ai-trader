-- ==========================================
-- MIGRATION: Add model_role column to ai_model_config
-- ==========================================
-- Supports multiple AI models for different tasks:
--   main     = Full analysis (BUY/SELL/WAIT decisions)
--   forecast = Quick position forecast (HOLD/CLOSE decisions)
--
-- Run: psql -U admin -d trading_log -f db/migrate_add_model_role.sql

-- Add model_role column (default 'main' for backward compatibility)
ALTER TABLE ai_model_config
    ADD COLUMN IF NOT EXISTS model_role VARCHAR(20) NOT NULL DEFAULT 'main';

-- Index for fast lookup by role + active
CREATE INDEX IF NOT EXISTS idx_ai_model_role_active
    ON ai_model_config (model_role, is_active);

-- Update existing rows: all current models are "main" role
UPDATE ai_model_config SET model_role = 'main' WHERE model_role IS NULL OR model_role = '';

-- Insert recommended models (user should update API keys)

-- DeepSeek V3.2 — Main analysis (smart, cheap)
INSERT INTO ai_model_config (provider, model, api_key, api_url, is_active, display_name, max_tokens, temperature, model_role, notes)
SELECT 'openrouter', 'deepseek/deepseek-v3.2',
       'sk-or-change-me',
       'https://openrouter.ai/api/v1/chat/completions',
       FALSE, 'DeepSeek V3.2 (Main Analysis)', 400, 0.10, 'main',
       'Smart and cheap ($0.26/$0.38 per 1M tokens). Good for full BUY/SELL/WAIT analysis.'
WHERE NOT EXISTS (SELECT 1 FROM ai_model_config WHERE model = 'deepseek/deepseek-v3.2' AND model_role = 'main');

-- Gemini 2.5 Flash-Lite — Quick forecast (ultra-fast, ultra-cheap)
INSERT INTO ai_model_config (provider, model, api_key, api_url, is_active, display_name, max_tokens, temperature, model_role, notes)
SELECT 'openrouter', 'google/gemini-2.5-flash-lite',
       'sk-or-change-me',
       'https://openrouter.ai/api/v1/chat/completions',
       FALSE, 'Gemini 2.5 Flash-Lite (Forecast)', 50, 0.05, 'forecast',
       'Ultra-low latency & cheap. Designed for rapid HOLD/CLOSE position forecasts every 20s.'
WHERE NOT EXISTS (SELECT 1 FROM ai_model_config WHERE model = 'google/gemini-2.5-flash-lite' AND model_role = 'forecast');

-- NVIDIA Llama 3.1 70B — Alternative main analysis
INSERT INTO ai_model_config (provider, model, api_key, api_url, is_active, display_name, max_tokens, temperature, model_role, notes)
SELECT 'nvidia', 'meta/llama-3.1-70b-instruct',
       'nvapi-change-me',
       'https://integrate.api.nvidia.com/v1/chat/completions',
       FALSE, 'Llama 3.1 70B (NVIDIA)', 400, 0.10, 'main',
       'Free tier from NVIDIA. Good alternative main model.'
WHERE NOT EXISTS (SELECT 1 FROM ai_model_config WHERE provider = 'nvidia' AND model = 'meta/llama-3.1-70b-instruct' AND model_role = 'main');
