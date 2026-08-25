-- Migration 040: Add hubspot_owner_id to user_personas
--
-- Purpose: Enable owner ID → email resolution without hardcoded mapping
--
-- Context: etl_meetings.py needs to resolve HubSpot meeting owner IDs to emails.
-- Currently uses hardcoded OWNER_EMAIL_MAP which creates two sources of truth
-- that drift. This column allows lookups against user_personas instead.
--
-- Populated by: seed_personas_from_config.py (reads from config/client.yaml team roster)
-- or manually via Supabase dashboard for initial setup.
--
-- Dependencies: Migration 033 (user_personas table exists)

ALTER TABLE user_personas
ADD COLUMN IF NOT EXISTS hubspot_owner_id TEXT;

-- Index for fast lookups by owner ID (used by etl_meetings.py)
CREATE INDEX IF NOT EXISTS user_personas_hubspot_owner_id_idx
    ON user_personas(hubspot_owner_id)
    WHERE hubspot_owner_id IS NOT NULL;

-- Comment for documentation
COMMENT ON COLUMN user_personas.hubspot_owner_id IS
'HubSpot owner ID (numeric string like ''87573414''). Used by ETL scripts to resolve
meeting/deal ownership to email. Nullable - not all users have HubSpot accounts.
Populated from config/client.yaml team roster or HubSpot Users API.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 040 complete - added hubspot_owner_id to user_personas';
    RAISE NOTICE 'Column is nullable and indexed for ETL owner resolution';
END $$;
