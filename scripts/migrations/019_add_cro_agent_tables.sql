-- Migration 019: CRO Agent tables and views
-- Phase G: Slack agent infrastructure for RevOps Q&A

-- ============ quota hierarchy ============
CREATE TABLE IF NOT EXISTS rep_targets (
  id            BIGSERIAL PRIMARY KEY,
  period        TEXT NOT NULL,        -- 'Q3_FY2027'
  level         TEXT NOT NULL,        -- 'company'|'team'|'rep'
  entity_name   TEXT NOT NULL,        -- 'YourCompany'|'AE Team'|'Jessica Smith'
  entity_email  TEXT,                 -- null for team/company
  role          TEXT,                 -- 'ae'|'am'|null for rollups
  metric        TEXT NOT NULL,        -- 'new_arr'|'expansion_arr'|'total_arr'
  target_value  NUMERIC NOT NULL,
  parent_entity TEXT,                 -- entity_name of level above
  set_by_slack  TEXT,                 -- Slack user_id of who set it
  set_at        TIMESTAMPTZ DEFAULT now(),
  UNIQUE (period, level, entity_name, metric)
);

-- ============ unanswered query log ============
CREATE TABLE IF NOT EXISTS unanswered_queries (
  id           BIGSERIAL PRIMARY KEY,
  question     TEXT NOT NULL,
  asked_by     TEXT,                  -- Slack user_id
  channel_id   TEXT,
  thread_ts    TEXT,
  reason       TEXT,                  -- 'no_data'|'out_of_scope'|'ambiguous'
  asked_at     TIMESTAMPTZ DEFAULT now()
);

-- ============ thread conversation history ============
CREATE TABLE IF NOT EXISTS conversation_threads (
  thread_ts    TEXT PRIMARY KEY,
  channel_id   TEXT NOT NULL,
  history      JSONB DEFAULT '[]',    -- [{role,content}, ...]
  last_active  TIMESTAMPTZ DEFAULT now(),
  expires_at   TIMESTAMPTZ DEFAULT now() + interval '24 hours'
);
CREATE INDEX IF NOT EXISTS idx_threads_expires
  ON conversation_threads(expires_at);

-- ============ arr_by_customer view ============
CREATE OR REPLACE VIEW arr_by_customer AS
SELECT
  company_name,
  SUM(deal_value)   AS total_arr,
  COUNT(*)          AS won_deal_count,
  MAX(close_date)   AS most_recent_close
FROM deals
WHERE deal_status = 'won'
GROUP BY company_name
ORDER BY total_arr DESC;
