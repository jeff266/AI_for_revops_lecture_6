-- Migration 025: Result cache layer for aggregate handler follow-ups
-- Separates what gets SHOWN (synthesis) from what gets RETAINED (detail).
-- Enables follow-ups on handlers like query_waterfall that return aggregates
-- with no deal_id/company_name fields.

-- Idempotent: safe to re-run if partial apply or double-run occurs
CREATE TABLE IF NOT EXISTS result_cache (
    result_key    TEXT PRIMARY KEY,
    thread_ts     TEXT NOT NULL,
    handler_name  TEXT,
    question      TEXT,
    payload       JSONB NOT NULL,
    row_count     INTEGER,
    created_at    TIMESTAMPTZ DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_result_cache_thread
    ON result_cache (thread_ts);
CREATE INDEX IF NOT EXISTS idx_result_cache_expires
    ON result_cache (expires_at);

-- Housekeeping view: what's live right now
CREATE OR REPLACE VIEW result_cache_active AS
SELECT result_key, thread_ts, handler_name, question,
       row_count, created_at, expires_at
FROM result_cache
WHERE expires_at > now()
ORDER BY created_at DESC;

SELECT pg_notify('pgrst', 'reload schema');
