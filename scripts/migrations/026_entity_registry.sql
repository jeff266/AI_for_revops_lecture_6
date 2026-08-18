-- Migration 026: Entity Registry
-- Extends data_dictionary to be the single source of truth for what counts as an entity.
-- This allows the system to support new entity types (campaign, account, ticket) without
-- code changes — just insert a row here.

ALTER TABLE data_dictionary
    ADD COLUMN IF NOT EXISTS is_entity_id BOOLEAN DEFAULT FALSE;

ALTER TABLE data_dictionary
    ADD COLUMN IF NOT EXISTS entity_type TEXT;
    -- e.g. 'deal', 'company', 'call', 'campaign'

ALTER TABLE data_dictionary
    ADD COLUMN IF NOT EXISTS entity_label_column TEXT;
    -- human-readable label for this ID, e.g.
    -- deals.deal_id -> 'company_name'

CREATE INDEX IF NOT EXISTS idx_data_dictionary_entity
    ON data_dictionary (is_entity_id)
    WHERE is_entity_id = TRUE;

-- Register the entities that exist TODAY. Adding a row here
-- is how a future entity type gets supported — no code change.
UPDATE data_dictionary
SET is_entity_id = TRUE, entity_type = 'deal',
    entity_label_column = 'company_name'
WHERE supabase_table = 'deals' AND supabase_column = 'deal_id';

UPDATE data_dictionary
SET is_entity_id = TRUE, entity_type = 'company',
    entity_label_column = 'company_name'
WHERE supabase_table = 'deals' AND supabase_column = 'company_id';

UPDATE data_dictionary
SET is_entity_id = TRUE, entity_type = 'call',
    entity_label_column = 'title'
WHERE supabase_table = 'calls' AND supabase_column = 'call_id';

-- Convenience view for the code to read
CREATE OR REPLACE VIEW entity_registry AS
SELECT supabase_table, supabase_column AS id_column,
       entity_type, entity_label_column, description
FROM data_dictionary
WHERE is_entity_id = TRUE;

SELECT pg_notify('pgrst', 'reload schema');
