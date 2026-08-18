# Port History Documentation

This directory contains historical documentation from the production → template port that created this repo.

## Files

**TEMPLATE_PORT_SCOPE.md** - Initial gap analysis comparing production (jeffignacio-growthbook/MEDDICC-agent) against template (jeff266/AI_for_revops_lecture_6). Identified what needed porting:
- Migrations 018-027
- Complete /api/ directory
- Eval test scripts
- Enrichment scripts
- Configuration compatibility analysis

**TEMPLATE_PORT_SUMMARY.md** - Port completion summary documenting:
- What was ported (34 files, ~8,500 lines)
- Stage requirements architectural fix (order-based, not hardcoded IDs)
- Config-driven design eliminating all GrowthBook-specific logic

**PORT_COMPLETE.md** - In-repo port documentation covering:
- All ported files and their purpose
- Config-driven stage requirements methodology
- Verification checklist
- Next steps for template activation

**CRO_AGENT_PORT_COMPLETE.md** - Phase 2 port completion:
- Missing API modules (time_resolver, assessor, rubric, schema_context, main, tools)
- Missing dependency (supabase_client)
- FastAPI server setup
- What was scrubbed (GrowthBook stage IDs, company names)
- Import verification results

## Port Timeline

1. **2026-08-17 17:18** - Initial port (commit 9761550)
   - Migrations 018-027
   - Partial /api/ directory (6 files)
   - All eval scripts
   - All enrichment scripts

2. **2026-08-17 17:39** - Complete CRO agent (commit ae960f4)
   - 7 missing API modules
   - supabase_client dependency
   - FastAPI server
   - Requirements.txt updates

3. **2026-08-17 17:47** - Config-driven call intent (commit 4514c8b)
   - call_intent_classifier internal identity from config

4. **2026-08-17 18:08** - README (commit b8101a3)
   - Comprehensive documentation for forkers

## Key Architectural Decisions

**Config-driven stage requirements:**
Instead of hardcoded stage IDs, `stage_requirements.py` uses `stage.order` from config. This allows the template to work for any client's HubSpot stage configuration without code changes.

**Zero scrubbing needed:**
The architectural fix eliminated the need for template-specific stage ID mappings. All code is genuinely generic and works for any client by reading `config/client.yaml`.

---

These documents are preserved for reference but describe completed work. For current setup instructions, see the main [README.md](../../README.md).
