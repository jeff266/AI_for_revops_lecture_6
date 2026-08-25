-- Migration 037: Create SDR metrics tables
-- Ported from GrowthBook migration 028
--
-- Purpose: Track daily SDR activity metrics across dialer/sequencer platforms
-- Enables SDR performance tracking, activity trending, and team benchmarking.
--
-- Usage: Tables are always created but remain empty unless client configures
-- Apollo, Salesloft, or Aircall. The ETL (scripts/etl_sdr_metrics.py) checks
-- for API keys before running. API handlers check table emptiness before querying.
--
-- Consumed by:
-- - scripts/etl_sdr_metrics.py (Apollo/Salesloft/Aircall ETL)
-- - api/handlers.py (query_sdr_metrics handler)
-- - api/router.py (SDR metrics intent classification)
--
-- Data sources:
-- - Apollo Analytics API (calls, emails via dialer)
-- - Salesloft API (calls, emails via sequences)
-- - Aircall API (outbound call metrics)
--
-- Dependencies: None (standalone tables)

-- User mapping table to normalize user IDs across different tools
CREATE TABLE IF NOT EXISTS sdr_users (
  id                        BIGSERIAL PRIMARY KEY,
  tool                      TEXT NOT NULL,
  -- apollo | salesloft | aircall
  tool_user_id              TEXT NOT NULL,
  user_name                 TEXT,
  user_email                TEXT,
  -- Optional: map to internal user identifier
  internal_user_id          TEXT,
  first_seen                TIMESTAMPTZ DEFAULT now(),
  last_seen                 TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tool, tool_user_id)
);

-- Daily SDR metrics per user per tool
CREATE TABLE IF NOT EXISTS sdr_metrics (
  id                        BIGSERIAL PRIMARY KEY,
  tool                      TEXT NOT NULL,
  -- apollo | salesloft | aircall
  tool_user_id              TEXT NOT NULL,
  user_name                 TEXT,
  metric_date               DATE NOT NULL,
  -- Date in reporting timezone (not UTC)

  -- Call metrics (Apollo, Salesloft, Aircall)
  calls_made                INTEGER DEFAULT 0,
  connected_calls           INTEGER DEFAULT 0,
  connect_rate              NUMERIC,
  -- null when calls_made = 0 (data gap)
  voicemails                INTEGER DEFAULT 0,
  no_answers                INTEGER DEFAULT 0,
  missed_calls              INTEGER DEFAULT 0,
  bad_numbers               INTEGER DEFAULT 0,
  avg_duration_seconds      NUMERIC,

  -- Email metrics (Salesloft only)
  emails_sent               INTEGER DEFAULT 0,
  emails_opened             INTEGER DEFAULT 0,
  emails_replied            INTEGER DEFAULT 0,
  open_rate                 NUMERIC,
  -- null when emails_sent = 0 (data gap)
  reply_rate                NUMERIC,
  -- null when emails_sent = 0 (data gap)

  -- Metadata
  data_gap                  BOOLEAN DEFAULT FALSE,
  -- true when key denominators are 0 (no activity)
  etl_run_at                TIMESTAMPTZ DEFAULT now(),

  UNIQUE(tool, tool_user_id, metric_date)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_sdr_users_tool
  ON sdr_users(tool);

CREATE INDEX IF NOT EXISTS idx_sdr_users_internal
  ON sdr_users(internal_user_id)
  WHERE internal_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_tool
  ON sdr_metrics(tool);

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_date
  ON sdr_metrics(metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_user_date
  ON sdr_metrics(tool_user_id, metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_tool_date
  ON sdr_metrics(tool, metric_date DESC);

-- Comments for documentation
COMMENT ON TABLE sdr_users IS
'User mapping across SDR tools (Apollo, Salesloft, Aircall). Normalizes user IDs for
cross-tool analytics. Remains empty unless client configures these tools.';

COMMENT ON TABLE sdr_metrics IS
'Daily SDR activity metrics per user per tool. Populated by scripts/etl_sdr_metrics.py
when Apollo/Salesloft/Aircall API keys are configured. Remains empty otherwise.';

COMMENT ON COLUMN sdr_metrics.metric_date IS
'Date in reporting timezone (config.organization.timezone), not UTC. All SDR metrics
use reporting timezone for consistent day-boundary aggregation.';

COMMENT ON COLUMN sdr_metrics.data_gap IS
'True when denominators are zero (calls_made=0, emails_sent=0). Distinguishes "no
activity" from "metrics not tracked". Used to avoid dividing by zero in rate calculations.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 037 complete - created SDR metrics tables';
    RAISE NOTICE 'Tables: sdr_users, sdr_metrics';
    RAISE NOTICE 'Tables remain empty unless Apollo/Salesloft/Aircall configured';
END $$;
