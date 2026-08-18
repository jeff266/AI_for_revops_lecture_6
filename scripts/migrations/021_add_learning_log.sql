-- Migration 021: Add learning_log table for Phase G.3 response assessment
-- Logs correctness assessments and retry patterns for weekly learning report

CREATE TABLE IF NOT EXISTS learning_log (
  id              BIGSERIAL PRIMARY KEY,
  week_of         DATE NOT NULL DEFAULT CURRENT_DATE,
  question        TEXT NOT NULL,
  handler_used    TEXT,
  issue_type      TEXT,
    -- wrong_handler|wrong_table|missing_join|wrong_time_window|should_be_dynamic|data_gap|format_only
  suggested_fix   TEXT,
  retry_succeeded BOOLEAN,
  retries_used    INTEGER DEFAULT 0,
  logged_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_learning_week
  ON learning_log(week_of);
CREATE INDEX IF NOT EXISTS idx_learning_issue
  ON learning_log(issue_type);

-- Verify table structure
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'learning_log'
ORDER BY ordinal_position;
