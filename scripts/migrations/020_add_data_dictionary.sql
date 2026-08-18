-- Migration 020: Add data_dictionary table for Phase H dynamic queries
-- Run in Supabase SQL Editor: https://supabase.com/dashboard/project/[project-id]/sql

-- Data dictionary table: maps HubSpot properties to Supabase columns
-- Enables the CRO agent to query tables it hasn't been explicitly programmed for
CREATE TABLE IF NOT EXISTS data_dictionary (
  id              BIGSERIAL PRIMARY KEY,
  source          TEXT NOT NULL,
    -- 'hubspot' | 'supabase' | 'computed'
  hubspot_name    TEXT,
    -- HubSpot internal property name (e.g. 'new_revenue')
  hubspot_label   TEXT,
    -- HubSpot display label (e.g. 'New ARR')
  supabase_table  TEXT,
    -- Supabase table where this lives (e.g. 'deals')
  supabase_column TEXT,
    -- Supabase column name (e.g. 'new_arr')
  data_type       TEXT,
    -- 'text' | 'number' | 'boolean' | 'date' | 'enumeration'
  enum_values     JSONB,
    -- For enumerations: [{"value":"closedwon","label":"Closed Won"}]
  description     TEXT,
    -- What this field means, for the agent's context
  is_queryable    BOOLEAN DEFAULT true,
    -- false for internal/system columns agent shouldn't filter on
  population_pct  NUMERIC,
    -- % of deals where this field is non-null (from sampling)
  last_refreshed  TIMESTAMPTZ DEFAULT now(),
  UNIQUE (supabase_table, supabase_column)
);

CREATE INDEX IF NOT EXISTS idx_dict_supabase
  ON data_dictionary(supabase_table, supabase_column);
CREATE INDEX IF NOT EXISTS idx_dict_hubspot
  ON data_dictionary(hubspot_name);
CREATE INDEX IF NOT EXISTS idx_dict_queryable
  ON data_dictionary(is_queryable) WHERE is_queryable = true;

-- Verification query
-- Run this after executing the CREATE TABLE to confirm structure
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'data_dictionary'
-- ORDER BY ordinal_position;
