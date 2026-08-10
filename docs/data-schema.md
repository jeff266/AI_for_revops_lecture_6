# Data Schema — the 5-table Supabase contract

This schema is the API between repos. The nightly agent writes; the CRO
agent reads; ETL can be replaced by Fivetran/Airbyte and storage by
Snowflake as long as this contract holds.

The tables below are defined by the migrations in
`scripts/migrations/` — `001_initial_schema.sql`,
`002_add_deal_history.sql`, and `003_add_component_scores.sql`. Run them
with `scripts/setup_supabase.py`.

---

## `deals`

Active and closed deals mirrored from the CRM.

**Written by:** the deal ETL (`scripts/etl_deals.py` →
`SupabaseWriter.upsert_deal`), keyed on `deal_id`.
**Read by:** the CRO agent (pipeline coverage, forecast, win-rate
queries) and the nightly agent's deal index.

| Column | Type | Notes |
|---|---|---|
| `deal_id` | TEXT | Primary key (HubSpot deal id) |
| `company_name` | TEXT | NOT NULL |
| `company_slug` | TEXT | NOT NULL; join key to `calls` |
| `stage` | TEXT | Current pipeline stage |
| `pipeline` | TEXT | Pipeline id/name |
| `arr_usd` | NUMERIC | Incremental ARR |
| `close_date` | DATE | Expected/actual close date |
| `owner_email` | TEXT | Deal owner |
| `last_analyzed` | TIMESTAMPTZ | Last nightly analysis timestamp |
| `created_at` | TIMESTAMPTZ | Default NOW() |
| `updated_at` | TIMESTAMPTZ | Default NOW() |
| `deal_status` | TEXT | `active` / `won` / `lost` (migration 002) |
| `create_date` | DATE | Deal creation date (migration 002) |
| `days_to_close` | INTEGER | Null for active deals; set on close (migration 002) |

---

## `analyses`

One row per qualification analysis produced by the nightly agent.

**Written by:** the nightly agent (`scripts/run_nightly.py` →
`SupabaseWriter.insert_analysis`). Insert-only (history is retained).
**Read by:** the CRO agent (deal health, rep coaching, trend queries).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `deal_id` | TEXT | FK → `deals(deal_id)` ON DELETE CASCADE |
| `company_name` | TEXT | NOT NULL |
| `analyzed_at` | TIMESTAMPTZ | Default NOW() |
| `overall_score` | INTEGER | Sum of component scores |
| `status` | TEXT | `red` / `yellow` / `green` |
| `metrics_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `economic_buyer_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `decision_criteria_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `decision_process_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `pain_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `champion_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `competition_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `iterations` | INTEGER | Generator/evaluator loop count (default 1) |
| `passed` | BOOLEAN | Whether the analysis passed evaluation |
| `full_analysis_text` | TEXT | The generated markdown analysis |
| `summary` | TEXT | 2-sentence summary |
| `output_file` | TEXT | Filename written under `output/` |
| `component_scores` | JSONB | Methodology-agnostic per-component scores (migration 003) |

The seven legacy `*_score` columns are populated only when the
configured methodology is MEDDICC. For every methodology, the
`component_scores` JSONB holds all per-component scores keyed by
`component_key` (e.g. `{"situation": 7, "pain": 8}` for SPICED). A GIN
index on `component_scores` supports containment queries.

---

## `calls`

One row per ingested call, with cheap signal flags.

**Written by:** the calls ETL (`scripts/etl_calls.py` →
`SupabaseWriter.bulk_upsert_calls`), keyed on `call_id`.
**Read by:** the CRO agent and objection/feature-gap analytics.

| Column | Type | Notes |
|---|---|---|
| `call_id` | TEXT | Primary key |
| `company_slug` | TEXT | NOT NULL; join key to `deals` |
| `company_name` | TEXT | |
| `source` | TEXT | NOT NULL; adapter name (`fireflies`, `gong`, `apollo`, …) |
| `call_date` | DATE | |
| `duration_minutes` | NUMERIC | |
| `title` | TEXT | |
| `formatted_summary` | TEXT | Analysis-ready summary (cache contract field) |
| `competitors_mentioned` | TEXT | |
| `has_feature_gap` | BOOLEAN | Default FALSE; keyword-detected |
| `has_objection` | BOOLEAN | Default FALSE; keyword-detected |
| `created_at` | TIMESTAMPTZ | Default NOW() |
| `updated_at` | TIMESTAMPTZ | Default NOW() |

---

## `objections`

Structured objections extracted from calls.

**Written by:** downstream objection-extraction (objection vault /
CRO agent) — the nightly agent in this repo does not populate it; the
table is part of the shared contract.
**Read by:** the CRO agent (objection vault, rep coaching).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `call_id` | TEXT | FK → `calls(call_id)` |
| `company_slug` | TEXT | |
| `rep_email` | TEXT | |
| `category` | TEXT | switching cost / budget / timing / technical / … |
| `verbatim_quote` | TEXT | Prospect's exact words |
| `rep_response` | TEXT | How the rep responded |
| `stage_when_raised` | TEXT | Pipeline stage the objection appeared at |
| `created_at` | TIMESTAMPTZ | Default NOW() |

---

## `rep_performance`

Per-rep, per-period rollups.

**Written by:** downstream rep-analytics (CRO agent) — not populated by
the nightly agent in this repo; part of the shared contract.
**Read by:** the CRO agent (rep scorecards, ramp analysis).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `rep_email` | TEXT | NOT NULL |
| `period_start` | DATE | NOT NULL |
| `period_end` | DATE | NOT NULL |
| `calls_count` | INTEGER | Default 0 |
| `deals_analyzed` | INTEGER | Default 0 |
| `meddicc_avg_score` | NUMERIC | Avg overall qualification score |
| `champion_avg_score` | NUMERIC | |
| `economic_buyer_avg_score` | NUMERIC | |
| `discovery_avg_score` | NUMERIC | |
| `created_at` | TIMESTAMPTZ | Default NOW() |

Unique on `(rep_email, period_start)`.

---

## `objections` / `feature_gaps` / `enrichment_scans`

Populated by `scripts/enrichment/*.py`, which read call summaries from `memory/calls/*.json` — NOT from the `calls` table. Rationale: the file cache is the fuzzy-matched, company-slugged source the analysis agent already uses; the `calls` table is a thinner sync whose company names are parsed from call titles and which has no deal association.

Scans are filtered to cache files whose slug matches a company with at least one deal, so a scanned call always has a possible deal association. `deal_id` is populated best-effort: when the company has exactly one deal, or exactly one deal whose lifetime covers the call date. Otherwise NULL — meaning genuine multi-deal ambiguity, not missing data. Rows are always anchored to `company_name`, which is taken from the matched deal (HubSpot-sourced), not from the cache file's title-derived field.

`enrichment_scans` is the dedup ledger (PK: call_id + job). A row with items_found = 0 means "scanned, found nothing" — distinct from never scanned.
