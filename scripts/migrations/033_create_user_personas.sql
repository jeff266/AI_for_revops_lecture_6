-- Migration 033: Create user_personas table
-- Merged from the reference implementation 029+032 (fold-forward pattern)
--
-- Purpose: User personas for voice-aware agent responses
-- Captures role, experience level, and preferred communication style
-- Used by API router to adapt response voice and detail level
--
-- IMPORTANT: This migration uses email as PRIMARY KEY from the start.
-- the reference implementation's 029 created it with id as PK and slack_user_id as UNIQUE NOT NULL,
-- then 032 redesigned to use email as PK with slack_user_id nullable (lazy binding).
-- The template gets the final schema without the intermediate state.
--
-- Seeding: Populated from HubSpot Users API. Slack IDs added lazily on first
-- message via email lookup.
--
-- Dependencies: None (standalone table)

CREATE TABLE IF NOT EXISTS user_personas (
  email                     TEXT PRIMARY KEY,
    -- Always known from HubSpot Users API

  slack_user_id             TEXT UNIQUE,
    -- U12345ABC format from Slack. Nullable - added lazily on first Slack message.

  display_name              TEXT,
  name                      TEXT,
  title                     TEXT,

  -- Role classification (from HubSpot or config overrides)
  role                      TEXT,
    -- Specific role: ae, sdr, vp_revops, cro, etc.
    -- Inferred from deal ownership patterns or config.team_roster overrides

  role_group                TEXT,
    -- Persona group for voice routing: ic, sales_leadership, operational, executive, other

  persona                   TEXT,
    -- Legacy field - same as role_group. Kept for backward compatibility.
    -- New code should use role_group.

  -- Metadata for adaptive responses
  preferred_detail_level    TEXT DEFAULT 'standard',
    -- brief | standard | detailed
  wants_metrics_context     BOOLEAN DEFAULT true,
    -- true: include "why this matters" framing
    -- false: just the numbers

  -- Tracking
  registered_at             TIMESTAMPTZ DEFAULT now(),
  last_seen_at              TIMESTAMPTZ DEFAULT now(),
  updated_at                TIMESTAMPTZ DEFAULT now(),
  source                    TEXT DEFAULT 'hubspot'
    -- hubspot | dm_intake | admin_seed
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS user_personas_slack_user_id_idx
    ON user_personas(slack_user_id) WHERE slack_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_personas_role_group_idx
    ON user_personas(role_group);

CREATE INDEX IF NOT EXISTS user_personas_role_idx
    ON user_personas(role);

-- Comments for documentation
COMMENT ON TABLE user_personas IS
'User personas seeded from HubSpot Users API. Slack IDs added lazily on first message
via email lookup. Used by API router for voice-aware response adaptation.';

COMMENT ON COLUMN user_personas.email IS
'Primary key. Always known from HubSpot. Used for email→slack_user_id lazy binding.';

COMMENT ON COLUMN user_personas.slack_user_id IS
'Added lazily when user sends first Slack message. Nullable until then. Unique constraint
allows fast lookup once populated.';

COMMENT ON COLUMN user_personas.role IS
'Specific role: ae, sdr, vp_revops, cro, etc. Inferred from deal ownership patterns in
HubSpot or set via config.team_roster overrides.';

COMMENT ON COLUMN user_personas.role_group IS
'Persona group for voice routing: ic (individual contributor), sales_leadership,
operational (revops/ops), executive (C-level), other. Maps to voice patterns in API router.';

COMMENT ON COLUMN user_personas.persona IS
'Legacy field - same as role_group. Kept for backward compatibility with older code.
New implementations should use role_group.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 033 complete - created user_personas table';
    RAISE NOTICE 'Uses email as PRIMARY KEY (lazy Slack binding)';
    RAISE NOTICE 'Seeded from HubSpot Users API, Slack IDs added on first message';
END $$;
