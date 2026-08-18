# Template Port Scope: Production → Template Gap Analysis

**Production Repo:** jeffignacio-growthbook/MEDDICC-agent (current checkout)
**Template Repo:** jeff266/AI_for_revops_lecture_6 (commit 60d2893)

---

## 1. MIGRATION GAP

**Template Highest Migration:** 017_add_backfill_confidence.sql
**Production Highest Migration:** 027_entity_scope_patterns.sql

### Missing in Template (Migrations 018-027):

| Migration | Purpose | Classification |
|-----------|---------|----------------|
| 018_add_component_rationales.sql | Component-level evidence storage | **Generic - Port** |
| 019_add_cro_agent_tables.sql | CRO Slack agent infrastructure | **Generic - Port** |
| 020_add_data_dictionary.sql | Self-documenting schema | **Generic - Port** |
| 021_add_learning_log.sql | Agent learning/improvement tracking | **Generic - Port** |
| 022_add_sales_signals_and_category_monitor.sql | Deal risk + competitive signals | **Generic - Port** |
| 023_calls_resolution_table.sql | Call-to-deal matching resolution | **Generic - Port** |
| 024_add_company_domain.sql | Domain field for enrichment | **Generic - Port** |
| 025_result_cache.sql | G.7 pronoun follow-up cache | **Generic - Port** |
| 026_entity_registry.sql | G.8 entity extraction registry | **Generic - Port** |
| 027_entity_scope_patterns.sql | G.8 bulk handler learning | **Generic - Port** |

**Recommendation:** All 10 migrations are generic agent capabilities, not GrowthBook-specific. Port all to template.

---

## 2. FILE-LEVEL DIVERGENCE

### Entire `/api/` Directory: PRODUCTION-ONLY

The template has **NO** `/api/` directory. Production has the full CRO Slack agent implementation:

| File | Lines | Purpose | Classification |
|------|-------|---------|----------------|
| api/router.py | 1,278 | Main routing, intent classification, synthesis | **Generic - Port (scrub examples)** |
| api/handlers.py | 961 | 18 precomputed query handlers | **Generic - Port (scrub stage IDs)** |
| api/db.py | 535 | Entity extraction, cache, logging | **Generic - Port** |
| api/evaluator.py | 87 | Result quality evaluation | **Generic - Port** |
| api/table_classifier.py | 91 | Dynamic SQL table routing | **Generic - Port** |
| api/stage_requirements.py | 149 | G.10 stage-aware risk logic | **Generic - Port** |

**Recommendation:** Port entire `api/` directory. Scrub:
- Stage IDs in handlers.py (replace with template placeholders)
- Example company names in router.py voice exemplar
- GrowthBook-specific handler logic (if any)

### Eval Test Scripts: PRODUCTION-ONLY

Template has no eval scripts. Production has comprehensive test coverage:

| File | Lines | Purpose | Classification |
|------|-------|---------|----------------|
| scripts/eval_entity_paths.py | 674 | 27 entity path regression tests | **Generic - Port** |
| scripts/eval_handler_descriptions.py | ~100 | Handler registry completeness | **Generic - Port** |
| scripts/eval_entity_extraction_dedup.py | ~150 | G.6 dedup fix regression | **Generic - Port** |
| scripts/eval_query_deal_stages_bulk.py | ~140 | G.10 Fix A regression | **Generic - Port** |
| scripts/eval_stage_aware_risk.py | ~300 | G.10 Fix B stage-aware risk | **Generic - Port** |
| scripts/eval_voice_layer.py | ~240 | G.9 voice instruction tests | **Generic - Port** |
| scripts/eval_waterfall_pipeline_summary.py | ~260 | Pipeline summary tests | **Generic - Port** |
| scripts/eval_duplicate_guard.py | ~80 | Cache dedup guard | **Generic - Port** |
| scripts/eval_entity_aware_extraction.py | ~100 | Entity-aware extraction | **Generic - Port** |

**Recommendation:** Port all eval scripts. These are pure logic tests with no GrowthBook-specific data.

### Enrichment Scripts Gap

**Production:** 9 enrichment scripts
**Template:** 2 enrichment scripts (extract_feature_gaps.py, extract_objections.py)

**Production-Only Scripts (7):**

| Script | Purpose | Classification |
|--------|---------|----------------|
| apollo_participants.py | Apollo.io call participant extraction | **Generic - Port** |
| fireflies_participants.py | Fireflies call participant extraction | **Generic - Port** |
| call_intent_classifier.py | Classify call type (discovery, demo, etc.) | **Generic - Port** |
| category_gap_detector.py | Feature gap categorization | **Generic - Port** |
| extract_sales_signals.py | Risk/competitive signals from calls | **Generic - Port** |
| resolve_calls.py | Call-to-deal matching resolution | **Generic - Port** |
| run_backfill.py | Orchestrator for backfill operations | **Generic - Port** |

**Recommendation:** All 7 are generic enrichment capabilities. Port all.

---

## 3. CONFIG SCHEMA GAP

**Template Config Schema:** ✅ **SUPPORTS ALL REQUIRED FEATURES**

| Feature | Template Support | Production Usage |
|---------|------------------|------------------|
| `internal_domains` | ✅ Line 13 | Used in G.4 call participant filtering |
| `stage_progression` | ✅ Line 209 | Used in G.10 stage-aware risk |
| `exclude_from_analysis` | ✅ Line 96-147 | Used throughout G.1-G.10 |
| `is_primary` pipeline flag | ✅ Line 141 | CRO agent default pipeline |
| `qualified_stage_order` | ✅ Line 122 | Win rate denominator |
| Segmentation config | ✅ Line 34-68 | Pipeline generation analytics |
| Fiscal year config | ✅ Line 30-31 | Quarterly reporting |

**No config schema changes needed.** Template already has the complete schema shape from G.1-G.10 sessions.

**Note:** Template does NOT have `internal_company_tokens` (was in GrowthBook production config for "GB", "GrowthBook" filtering). This was GrowthBook-specific and should NOT be ported — `internal_domains` is the generic equivalent.

---

## 4. NEW TABLES/VIEWS NOT IN TEMPLATE

Template has 12 tables. Production has 23 tables. **11 tables missing in template:**

| Table | Migration | Purpose | Classification |
|-------|-----------|---------|----------------|
| `conversation_threads` | 019 | Multi-turn context tracking | **Generic - Port** |
| `data_dictionary` | 020 | Schema documentation | **Generic - Port** |
| `learning_log` | 021 | Agent improvement patterns | **Generic - Port** |
| `competitive_signals` | 022 | Competitor mentions from calls | **Generic - Port** |
| `deal_risks` | 022 | Risk factor extraction | **Generic - Port** |
| `pipeline_signals` | 022 | Pipeline movement patterns | **Generic - Port** |
| `rep_targets` | 019 | Quota/target tracking | **Generic - Port** |
| `result_cache` | 025 | Pronoun follow-up cache | **Generic - Port** |
| `entity_scope_patterns` | 027 | Bulk handler learning | **Generic - Port** |
| `unanswered_queries` | 019 | CRO agent failure tracking | **Generic - Port** |
| `entity_registry` | 026 | Entity extraction patterns | **Generic - Port** |

**Recommendation:** All 11 tables are generic agent capabilities. Port all migrations.

### Tables Present in Both (No Changes Needed)

- `analyses` ✅
- `calls` ✅ (but production has E.3 rebuild — check schema)
- `deals` ✅
- `deals_snapshot` ✅
- `enrichment_scans` ✅
- `feature_gaps` ✅
- `forecast_weekly` ✅
- `objections` ✅
- `pipeline_generation_weekly` ✅
- `rep_performance` ✅
- `waterfall_weekly` ✅
- `win_loss_narratives` ✅

---

## 5. SUMMARY: PORT SCOPE BY CATEGORY

### A. Port As-Is (No Scrubbing Needed)

- Migrations 018-027 (10 migrations)
- api/db.py
- api/evaluator.py
- api/table_classifier.py
- api/stage_requirements.py
- All 9 eval test scripts
- Config schema (already compatible)

### B. Port with Scrubbing (Replace GrowthBook-Specific Data)

**api/router.py** (1,278 lines):
- Scrub: Voice exemplar company names (GrowthBook, LaunchDarkly examples)
- Keep: All routing logic, intent classification, REPORT_SHAPES, synthesis

**api/handlers.py** (961 lines):
- Scrub: Stage IDs in query_waterfall, query_deals_at_risk (replace with template placeholders)
- Scrub: Any hardcoded GrowthBook stage names
- Keep: All 18 handler implementations

**scripts/enrichment/*.py** (9 scripts):
- Audit each: determine if generic (port) vs provider-specific (skip/scrub)

### C. GrowthBook-Specific (Do NOT Port)

- None identified so far
- internal_company_tokens config field (not in template, good)

### D. Needs Investigation

- ✅ **Enrichment scripts** (RESOLVED): All 7 are generic, port all
- ✅ **Calls table schema** (RESOLVED): Identical in both repos, no changes needed
- ⚠️ **Handler-specific logic**: Quick review recommended for any GrowthBook-specific filters in api/handlers.py (though none expected based on G.1-G.10 session focus on generic methodology)

---

## 6. RECOMMENDED PORT ORDER

1. **Migrations 018-027** (foundation for everything else)
2. **api/stage_requirements.py** (standalone, no dependencies)
3. **api/table_classifier.py** (standalone)
4. **api/evaluator.py** (standalone)
5. **api/db.py** (depends on migrations)
6. **api/handlers.py** (depends on stage_requirements, db)
7. **api/router.py** (depends on handlers, evaluator)
8. **All eval scripts** (depend on api/* being in place)
9. **Enrichment scripts** (after audit)

---

## 7. ESTIMATED EFFORT

**High Confidence (Low Risk):**
- Migrations: 30 minutes (run sequentially, verify)
- Standalone modules (stage_requirements, evaluator, table_classifier): 15 minutes
- api/db.py: 20 minutes
- Eval scripts: 10 minutes (copy as-is)

**Medium Confidence (Requires Scrubbing):**
- api/handlers.py: 45 minutes (replace stage IDs with template values)
- api/router.py: 30 minutes (scrub voice exemplar)

**Needs Investigation:**
- Enrichment scripts: 60 minutes (audit + selective port)

**Total Estimated Time:** 3-4 hours for complete port

---

## 8. VERIFICATION CHECKLIST

After porting, verify:
- [ ] All 27 migrations run cleanly in order
- [ ] Config schema loads without errors
- [ ] All 9 eval scripts pass
- [ ] api/router.py has no GrowthBook references
- [ ] api/handlers.py uses template stage IDs
- [ ] Enrichment scripts use generic examples
- [ ] Railway deployment succeeds
- [ ] Test query in Slack returns sensible results

---

**Next Step:** Review this report and decide which sections to port first. Recommend starting with migrations 018-027 to establish database foundation.
