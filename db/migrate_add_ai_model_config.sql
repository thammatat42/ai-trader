-- ==========================================
-- MIGRATION: Add ai_model_config table
-- ==========================================
-- Allows switching AI models from Dashboard without restart

CREATE TABLE IF NOT EXISTS ai_model_config (
    id              SERIAL PRIMARY KEY,
    provider        VARCHAR(20)   NOT NULL,           -- openrouter / nvidia
    model           VARCHAR(100)  NOT NULL,
    api_key         VARCHAR(200)  NOT NULL,
    api_url         VARCHAR(300)  NOT NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT FALSE,
    display_name    VARCHAR(100),                     -- friendly name for dashboard
    max_tokens      INTEGER       DEFAULT 400,
    temperature     NUMERIC(3,2)  DEFAULT 0.10,
    notes           TEXT,
    created_at      TIMESTAMP     DEFAULT NOW(),
    updated_at      TIMESTAMP     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_model_active ON ai_model_config (is_active);

-- Insert default models from common env vars (user should update API keys)
INSERT INTO ai_model_config (provider, model, api_key, api_url, is_active, display_name, max_tokens, temperature)
SELECT 'nvidia', 'meta/llama-3.1-70b-instruct',
       'nvapi-change-me',
       'https://integrate.api.nvidia.com/v1/chat/completions',
       TRUE, 'Llama 3.1 70B (NVIDIA)', 400, 0.10
WHERE NOT EXISTS (SELECT 1 FROM ai_model_config WHERE provider = 'nvidia' AND model = 'meta/llama-3.1-70b-instruct');

INSERT INTO ai_model_config (provider, model, api_key, api_url, is_active, display_name, max_tokens, temperature)
SELECT 'openrouter', 'anthropic/claude-3-haiku',
       'sk-or-change-me',
       'https://openrouter.ai/api/v1/chat/completions',
       FALSE, 'Claude 3 Haiku (OpenRouter)', 400, 0.10
WHERE NOT EXISTS (SELECT 1 FROM ai_model_config WHERE provider = 'openrouter' AND model = 'anthropic/claude-3-haiku');
