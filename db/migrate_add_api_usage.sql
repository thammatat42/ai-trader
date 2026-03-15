-- ==========================================
-- MIGRATION: Add api_usage_log table
-- ==========================================

CREATE TABLE IF NOT EXISTS api_usage_log (
    id                  SERIAL PRIMARY KEY,
    provider            VARCHAR(20)   NOT NULL,
    model               VARCHAR(100)  NOT NULL,
    prompt_tokens       INTEGER       DEFAULT 0,
    completion_tokens   INTEGER       DEFAULT 0,
    total_tokens        INTEGER       DEFAULT 0,
    response_time_ms    INTEGER       DEFAULT 0,
    status              VARCHAR(10)   DEFAULT 'OK',
    created_at          TIMESTAMP     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_created  ON api_usage_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage_log (provider);
