-- ============================================================
-- Phase E.2 — enrichment schema evolution
--   1. Sales signal tables for INTENT_SALES_REVIEW calls
--   2. other_category_monitor view
--   3. data_dictionary entries for the category columns
-- ============================================================

-- ============ sales signals from internal sales calls ============
-- deal_id is nullable on purpose: these signals come from
-- internal forecast/pipeline calls that often reference several
-- deals, or none that resolve to a single deal record.

CREATE TABLE IF NOT EXISTS deal_risks (
  id               BIGSERIAL PRIMARY KEY,
  call_id          TEXT NOT NULL,
  company_name     TEXT,
  deal_id          TEXT,
  risk_description TEXT NOT NULL,
  rep_name         TEXT,
  source_company   TEXT,          -- company slug of the call itself
  extracted_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_deal_risks_call
  ON deal_risks (call_id);
CREATE INDEX IF NOT EXISTS idx_deal_risks_company
  ON deal_risks (company_name);

CREATE TABLE IF NOT EXISTS competitive_signals (
  id              BIGSERIAL PRIMARY KEY,
  call_id         TEXT NOT NULL,
  competitor_name TEXT NOT NULL,
  context         TEXT,
  deal_company    TEXT,
  deal_id         TEXT,
  source_company  TEXT,
  extracted_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_comp_signals_call
  ON competitive_signals (call_id);
CREATE INDEX IF NOT EXISTS idx_comp_signals_name
  ON competitive_signals (competitor_name);

CREATE TABLE IF NOT EXISTS pipeline_signals (
  id            BIGSERIAL PRIMARY KEY,
  call_id       TEXT NOT NULL,
  signal_type   TEXT NOT NULL,
    -- 'commit_risk' | 'upside' | 'slip' | 'pull_in'
  company_name  TEXT,
  deal_id       TEXT,
  description   TEXT NOT NULL,
  source_company TEXT,
  extracted_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pipeline_signals_call
  ON pipeline_signals (call_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_signals_type
  ON pipeline_signals (signal_type);

-- ============ "other" category monitoring view ============
-- Lets the agent answer "how are our objection categories
-- distributed?" and see whether 'other' is growing.

CREATE OR REPLACE VIEW other_category_monitor AS
SELECT
  'objections' as source_table,
  category,
  count(*) as count,
  round(count(*)::numeric /
    sum(count(*)) over() * 100, 1) as pct_of_total,
  max(extracted_at) as latest
FROM objections
GROUP BY category

UNION ALL

SELECT
  'feature_gaps' as source_table,
  category,
  count(*) as count,
  round(count(*)::numeric /
    sum(count(*)) over() * 100, 1) as pct_of_total,
  max(extracted_at) as latest
FROM feature_gaps
GROUP BY category

ORDER BY source_table, count DESC;

-- ============ data dictionary entries ============
-- NOTE: data_dictionary.source is NOT NULL, so it must be
-- supplied here even though the category columns are plain
-- Supabase columns.

INSERT INTO data_dictionary (
  source, supabase_table, supabase_column, data_type,
  description, is_queryable
) VALUES (
  'supabase',
  'objections', 'category', 'text',
  'Objection category. Values: switching_cost, budget,
   timing, technical, internal_politics, product_gap,
   trust, build_vs_buy, other. If "other" exceeds 15%
   of total it signals emerging uncategorized patterns.',
  true
) ON CONFLICT (supabase_table, supabase_column)
DO UPDATE SET description = EXCLUDED.description;

INSERT INTO data_dictionary (
  source, supabase_table, supabase_column, data_type,
  description, is_queryable
) VALUES (
  'supabase',
  'feature_gaps', 'category', 'text',
  'Feature gap category. Values: reporting, integration,
   permissions_security, pricing_packaging,
   platform_capability, other. If "other" exceeds 15%
   of total it signals emerging uncategorized patterns.',
  true
) ON CONFLICT (supabase_table, supabase_column)
DO UPDATE SET description = EXCLUDED.description;

SELECT pg_notify('pgrst', 'reload schema');
