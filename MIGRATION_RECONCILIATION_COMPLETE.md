# Migration Reconciliation - Execution Summary

**Date:** 2026-08-24
**Status:** ✅ Step 1 Complete - All migrations ported and renumbered

## What Was Done

### 1. Four Fold-Forward Migrations Created

**Migration 017** (REPLACED - was broken)
- **Source:** GrowthBook 017+039 merged
- **Issue:** Original had old CHECK vocabulary that would fail with 23514 constraint violation
- **Fix:** Merged into single migration with correct vocabulary from start
- **Vocabulary:** `exact/pre_history/no_history` (+ legacy values for back-compat)
- **Why critical:** Reconstruction code writes 'pre_history'/'no_history' - old CHECK would reject these

**Migration 029** (NEW)
- **Source:** GrowthBook 037+038 merged
- **What:** fiscal_quarter, forecast_category, week_of_quarter on deals_snapshot
- **Fix:** fiscal_quarter as NOT NULL from start (GrowthBook added constraint later in 038)
- **Why:** Every snapshot must have fiscal_quarter - NULL orphans contaminate analyses

**Migration 032** (NEW)
- **Source:** GrowthBook 033+035 merged
- **What:** meetings table with call recording held inference
- **Fix:** Uses call_recording_id from start (not fireflies_call_id)
- **Why:** Supports multiple call adapters (Fireflies, Gong, Apollo) without migration

**Migration 033** (NEW)
- **Source:** GrowthBook 029+032 merged
- **What:** user_personas table for voice-aware agent responses
- **Fix:** email as PRIMARY KEY from start (not id + later redesign)
- **Why:** Enables lazy Slack ID binding on first message

### 2. Six Core Migrations Ported

**Migration 028** - Add sdr_owner_email to deals (GB 031)
- **CORE attribution field** - used by etl_deals.py and api handlers
- Every client needs this even if unpopulated

**Migration 030** - Create call_transcripts table (GB 041)
- **BLOCKING for etl_calls.py** (referenced 33 times)
- Separate table keeps calls table lean (transcripts are 40-60KB each)

**Migration 031** - Add transcript_metrics (GB 042)
- Conversation metrics (talk_time, question_count, monologue_length)
- Depends on migration 030

**Migration 034** - Add proposal_lifecycle to data_dictionary (GB 034)
- Enables agent to propose new field definitions
- Review workflow (draft → active → accepted/rejected)

**Migration 035** - Create proposals table (GB 036)
- Generic self-improvement recommendation ledger
- Agent proposes config changes, human approves
- NOT a live config source - approval triggers manual change

**Migration 036** - Create score_corrections table (GB 040)
- Rep feedback review queue for score disagreements
- Training signal for score improvement
- Never auto-adjusts live scores

### 3. Two Optional Migrations Ported

**Migration 037** - SDR metrics tables (GB 028) - **OPTIONAL**
- Creates sdr_users and sdr_metrics tables
- Only needed if client has Apollo/Salesloft/Aircall configured
- Skip if SDR metrics tracking not needed

**Migration 038** - Call quality table (GB 030) - **OPTIONAL**
- Discovery quality scoring (5 dimensions: quantification, incumbent, technical, decision process, question quality)
- Only needed if client wants discovery coaching feature
- Skip if call quality assessment not needed

## Final Migration Sequence

**Template migrations:** 001-027, 028-038, 043

**Clean sequence check:** ✅ No gaps except intentional 039-042 skip
- 039-042 were either folded forward (039→017, etc.) or optional features relocated

**Migration 043:** ✅ Already exists with CORRECT JSONB pattern
- Uses component_scores JSONB (methodology-agnostic)
- Better than GrowthBook's fixed columns (metrics_score, economic_buyer_score, etc.)
- No changes needed

## Renumbering Map

| Template # | GrowthBook Source | Type | Notes |
|------------|-------------------|------|-------|
| 017 | 017+039 merged | REPLACE | Correct CHECK vocabulary from start |
| 028 | 031 | Port | sdr_owner_email - CORE attribution |
| 029 | 037+038 merged | Fold-forward | fiscal_quarter NOT NULL from start |
| 030 | 041 | Port | call_transcripts - CORE (etl_calls.py) |
| 031 | 042 | Port | transcript_metrics |
| 032 | 033+035 merged | Fold-forward | meetings with call_recording_id |
| 033 | 029+032 merged | Fold-forward | user_personas email PK |
| 034 | 034 | Port | proposal_lifecycle |
| 035 | 036 | Port | proposals table |
| 036 | 040 | Port | score_corrections |
| 037 | 028 | Port (OPTIONAL) | sdr_metrics |
| 038 | 030 | Port (OPTIONAL) | call_quality |
| 043 | 043 (template) | Keep | Already correct JSONB pattern |

## Verification Performed

✅ **Fold-forward pairs verified** - Read both migrations, confirmed overlap, merged correctly
✅ **Core vs optional distinction** - Checked what consumes each table
✅ **Migration 017 blocking bug confirmed** - Old CHECK would fail with 23514
✅ **Migration 043 already correct** - Template has better pattern than GrowthBook
✅ **Sequence clean** - No gaps (except intentional), no duplicates
✅ **All files created** - 4 fold-forward + 6 core + 2 optional = 12 new migrations

## Next Steps (MIGRATION_ETL_RECONCILIATION.md Step 2-5)

### Step 2: Self-Verifying Tests
- [ ] Port no-duplicate-number test (eval_migrations.py)
- [ ] Create no-gap test (would have caught 028-042 missing)
- [ ] Port vocabulary agreement test (CHECK constraints match code writes)
- [ ] Create applied-state check (which migrations applied vs present)

### Step 3: Reconcile ETLs
- [ ] Diff etl_calls.py template vs GrowthBook
  - Fireflies transcript fetch (get_transcript_sentences)
  - Rate-limit backoff on GraphQL body errors
  - Source-priority dedup
  - Transcript persist to call_transcripts table
- [ ] Diff etl_deals.py template vs GrowthBook
  - Point-in-time field population
  - Inclusion rule (deal belongs in snapshot only if created by D and not terminal before D)
  - Verify reads history not current state

### Step 4: Point-in-Time Correctness
- [ ] Add module docstring to snapshot writer (invariant: every field as-of snapshot_date)
- [ ] Port guard test (fails if joins to live deals for historical row)
- [ ] Port get_field_at_date() helper with fixtures
- [ ] Test backward-moving case (deal regressing stage)
- [ ] Test no-history case (returns null, never default)

### Step 5: Verification Suite
- [ ] Port coverage check (fraction of deals with calls/transcripts/scores)
- [ ] Port determinism harness (score one call 5 times, report spread)
- [ ] Port reconciliation pattern (before/after counts, refuse commit on unexplained move)
- [ ] Port plausibility assertions (conversion >100%, subset larger than superset, etc.)
- [ ] Port CRM cross-check (agent counts vs CRM counts, explain difference)

## Files Modified

**Replaced:**
- scripts/migrations/017_add_backfill_confidence.sql (backup: .backup)

**Created:**
- scripts/migrations/028_add_sdr_owner_to_deals.sql
- scripts/migrations/029_add_fiscal_quarter_to_snapshots.sql
- scripts/migrations/030_create_call_transcripts.sql
- scripts/migrations/031_add_transcript_metrics.sql
- scripts/migrations/032_create_meetings_table.sql
- scripts/migrations/033_create_user_personas.sql
- scripts/migrations/034_add_proposal_lifecycle.sql
- scripts/migrations/035_create_proposals.sql
- scripts/migrations/036_add_score_corrections.sql
- scripts/migrations/037_add_sdr_metrics.sql (OPTIONAL)
- scripts/migrations/038_add_call_quality.sql (OPTIONAL)

**Backup:**
- scripts/migrations/017_add_backfill_confidence.sql.backup (original with old CHECK)

## Critical Issues Fixed

1. **23514 constraint violation prevented** - Migration 017 now has correct vocabulary
2. **Missing 15 migrations closed** - Template now has 028-038 (was 001-027, 043)
3. **etl_calls.py unblocked** - call_transcripts table now exists (migration 030)
4. **Methodology switching preserved** - Migration 043 already had JSONB pattern
5. **Fold-forward pattern established** - Template avoids inheriting wrong constraint + later fix

## Success Metrics

✅ **Clean sequence:** 001-038, 043 (no gaps except intentional)
✅ **No duplicates:** Each migration number used once
✅ **Fold-forward applied:** 4 correction pairs merged correctly
✅ **Optional marked:** 2 migrations clearly documented as skip-able
✅ **Blocking bug fixed:** Migration 017 will not fail with 23514
✅ **Dependencies respected:** Migration order preserves FK relationships

**Ready for Step 2:** Self-verifying test suite
