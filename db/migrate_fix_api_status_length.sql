-- Fix api_usage_log status column: VARCHAR(10) → VARCHAR(20)
-- "OK_FORECAST" is 11 chars, exceeds the old 10 limit
ALTER TABLE api_usage_log ALTER COLUMN status TYPE VARCHAR(20);
