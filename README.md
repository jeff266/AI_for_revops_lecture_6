# RevOps MEDDICC Agent

A revenue operations data substrate with an agent on top. The substrate reconstructs point-in-time pipeline history from CRM property history so you can ask what the pipeline looked like on any past date and get the real answer, not current state projected backward. The agent scores deals against a configurable sales methodology from call transcripts and answers questions in Slack.

**This has never been deployed against live client data.** It was ported from a working reference deployment, every client-specific reference was scrubbed and made config-driven, and 87 passing tests confirm the structure is sound. But no one has watched it run a full nightly cycle against fresh data. Edge cases may exist where a config key is read but not validated, or where a CRM API response shape differs from what the reference deployment sees.

---

## Pipeline history and analytics

Everything the Slack agent answers was produced by these batch jobs.

**Point-in-time snapshots** — Weekly forward snapshots (`scripts/analytics/snapshot_deals.py`) plus backfill from CRM property history (`scripts/etl/backfill_snapshots.py`). Both use the same inclusion rule so they cannot diverge. You can ask "what was the pipeline on March 15?" and get the real historical state, not today's deals with fabricated timestamps.

**Waterfall** — Beginning balance, newly qualified, moved forward, moved backward, won, lost, ending balance. Unknown deal values are excluded from dollar sums and counted separately (never zero-filled). `scripts/analytics/compute_waterfall.py` — 560 lines, null-propagation + point-in-time qualification.

**Forecast analytics** — Week-3 pipeline conversion rates, coverage curves (pipeline needed to hit quota), quarter pacing (`scripts/analytics/compute_pipeline_generation.py` and `compute_forecast.py`).

**Win/loss narratives** — Won, lost, and **slipped** as three outcomes (a deal that closed in a later quarter than committed is slipped, not lost — different diagnosis, different coaching). `scripts/analytics/generate_win_loss.py` — 358 lines, point-in-time semantics, min_evidence_count gate (below threshold returns null with reason rather than fabricating narrative from thin material).

**Pipeline generation by segment** — Per-segment (SMB/Mid-Market/Enterprise) pipeline generation with per-band cycle expectations from `config/client.yaml`. Embedded in `compute_pipeline_generation.py`. Note: segment-specific win rates, conversion rates, and velocity aren't isolated from pipeline generation in this version (design gap, not missing file).

**Call transcripts with speaker metrics** — Talk ratio, question count, longest monologue. Supports Fireflies (seconds), Apollo (milliseconds → seconds), and Gong (no timing data from API, so talk-time/monologue metrics unavailable). Units converted at boundary, speaker-attributed, consumers never know source. `scripts/transcript_store.py`.

---

## Deal scoring and the agent

**Progressive per-call MEDDICC scoring** — Each call updates component scores, accumulated to deal level via `scripts/context_builder.py` (Haiku cumulative state synthesis). Not a full-history re-read every time — carry-forward rule keeps context manageable.

**Configurable methodology** — MEDDICC, MEDDPICC, SPICED, or BANT. Switched in `config/client.yaml`, no code change. `scripts/get_components.py` reads the methodology and returns the right component list. Raises on unknown values (Gap 2 discipline: no silent fallbacks).

**Nightly scoring run** — `scripts/run_nightly.py` orchestrates: load deals → load calls → context builder (Haiku) → generator (Sonnet) → evaluator (Haiku) → reflection gate (Haiku) → write HubSpot + Supabase + learnings. GitHub Actions, 2am UTC daily.

**Slack agent** — 28 handlers (16 precomputed + 12 dynamic). Answers deal, rep, team, SDR, and pipeline questions. Intent classification → query → synthesis → self-assessment (correctness + tone) → retry if needed. FastAPI on Railway. See `api/router.py`, `api/handlers.py`.

---

## What you need before you start

Someone who has these answers ready completes onboarding in one sitting. Someone who does not stops halfway to go find them.

- **Sales methodology** — MEDDICC, MEDDPICC, SPICED, or BANT
- **Pipeline stages in order** — First contact to signature, not including closed won or closed lost. You need stage IDs, not display names. `scripts/discover_stages.py` finds them from your CRM.
- **Fiscal year start month** — Getting this wrong silently misplaces every quarter boundary. If your fiscal year starts February 1, this is `2`, not `1`.
- **Segment bands** — How you split SMB / Mid-Market / Enterprise. The CRM field it reads from (`numberofemployees`, `arr`, custom field). Rough cycle length per band in days.
- **Call tool** — Fireflies, Gong, or Apollo. API access credentials for whichever you use.
- **The CRM field holding deal value** — `amount`, `arr`, `incremental_arr`, custom field. Pipeline waterfall and forecast analytics read this field. If you point it at the wrong one, every dollar calculation is wrong.
- **Team roster** — Names, emails, roles, and CRM owner IDs. Used for persona-aware Slack responses (executive vs sales vs operational voice).

---

## Requirements

**CRM:** HubSpot or Salesforce. If Salesforce, you provide the adapter (documented interface in `scripts/adapters/crm/base.py`).

**Call intelligence:** Fireflies, Gong, or Apollo. Factory in `scripts/adapters/calls/__init__.py` reads `call_tools.primary` from config and instantiates the matching adapter. All three adapters are fully implemented.

**Database:** Supabase. 27 migrations in `scripts/migrations/`. Direct pooler connection string required for migrations (not just project URL + service key).

**Slack (optional):** Only needed if you want the query layer. You provide a Slack workspace and two Zapier zaps (inbound: Slack → Railway, outbound: Railway → Slack).

**Anthropic API:** Claude Sonnet 4.5 (generation, synthesis) + Claude Haiku 4.5 (classification, evaluation). ~$10-20/month for nightly + light Slack use.

**Someone who can:** Run Python, apply SQL migrations, set environment variables, configure GitHub Actions secrets, deploy to Railway (if using Slack agent).

If you do not have these, learn it here rather than at step seven.

---

## Start here

1. **`pip install -r requirements.txt`** — Python 3.10+, packages from `requirements.txt`

2. **Run the `revops-agent-setup` skill** — Credentials, secret hooks, environment variables. In Claude Code: open repo, say "set up this repo". In Claude.ai (web/mobile): paste `skills/revops-agent-setup/SKILL.md` into custom skill creator, say "start setup". Writes `.env` and prints GitHub Secrets checklist.

3. **Run the `revops-client-context` skill** — Methodology, stages, segments, competitors, objections. Say "start client onboarding". Writes `config/client.yaml`, `config/context.yaml`, `prompts/CLAUDE.md`, `prompts/evaluator_rubric.md`. References in `skills/revops-client-context/references/`.

4. **Apply migrations** — `python scripts/setup_supabase.py`. Requires `SUPABASE_DB_URL` in environment (direct pooler connection string). Migrations 001–027 build the full schema. Each migration executes, verifies a fingerprint object via scoped read, then records success. If verification fails, paste printed SQL into Supabase SQL editor and re-run. Audit any time with `python scripts/setup_supabase.py --verify-all`.

5. **`python scripts/verify/run_all.py`** — Expect INCONCLUSIVE before any data has loaded. That is correct, not broken. Plausibility checks return INCONCLUSIVE when tables are empty or below minimum thresholds. After first nightly run, re-run to see your actual numbers.

6. **First nightly run** — Set GitHub Secrets under the `Agent` environment (`gh secret set --env Agent --env-file .env`). Actions → MEDDICC Agent Nightly Run → Run workflow. First run analyzes full active pipeline (~$3-5). Subsequent runs analyze only changed deals (~$0.10-0.30/night).

7. **Re-run verification suite** — `python scripts/verify/run_all.py` now shows your data. Plausibility checks (conversion rates 0-100%, win rate 0-100%, cycle time non-negative, counts non-negative, subset ≤ superset) verify analytical outputs. See `scripts/verify/plausibility.py`.

**Optional — Slack agent (step 8):**

Deploy to Railway (`uvicorn api.main:app --host 0.0.0.0 --port $PORT`). Set environment variables (see table below). Build two Zapier zaps: inbound (Slack → POST `/slack/question` with `SLACK_RELAY_SECRET`), outbound (catch hook receives reply, posts to Slack thread). Put catch hook URL in `ZAP_REPLY_URL`. Message bot in Slack, confirm threaded reply.

---

## Read STATUS.md before trusting the numbers

**Provisional thresholds:** The correctness floor at 0.30 (`api/assessor.py`) and the stage-progression thresholds (`config/client.yaml`) are guesses carried from the reference deployment, not measurements from your business. A team with shorter calls or less structured discovery might need to lower the quality threshold; a team with deep enterprise cycles might raise it. Stage-progression thresholds (e.g., `identified_pain: 5`, `champion: 4` to move from Discovery to Scoping) reflect the reference deployment's qualification bar. Your team's bar may differ.

**The verification suite is how you find out what is true for your data.** Run `python scripts/verify/run_all.py` after first nightly run. Plausibility checks catch:
- Conversion rates outside 0-100%
- Win rates outside 0-100% or negative
- Cycle times negative
- Counts negative
- Subset counts exceeding superset (qualified > total, won > qualified)
- Waterfall reconciliation errors (ending ≠ beginning + net_change)

If plausibility checks fail, the analytical outputs have a bug. If they pass but numbers seem wrong, the thresholds need calibration. See `STATUS.md` Known Limitations and Untested sections.

---

## Architecture in brief

**Nightly (GitHub Actions):**
- 1:00 AM UTC: Deal ETL (`scripts/etl_deals.py` → `memory/deals/index.json`)
- 1:30 AM UTC: Calls ETL (`scripts/etl_calls.py` → `memory/calls/<slug>.json`)
- 2:00 AM UTC: MEDDICC agent (`scripts/run_nightly.py` → HubSpot + Supabase)
- Sunday 3:00 AM UTC: Weekly analytics (snapshots, waterfall, win/loss, forecast)

**Interactive (Railway + Zapier):**
- User messages bot in Slack
- Zapier catches message → POST `/slack/question` (Railway FastAPI)
- Intent classification → precomputed handler OR dynamic query
- Pull rows from Supabase → synthesize (Sonnet) → self-assess (Haiku) → retry if needed
- POST answer to `ZAP_REPLY_URL` → Zapier → Slack thread
- Thread context cached, follow-ups reuse entities

**Costs:**
- First full pipeline run: ~$3-5
- Nightly steady state: ~$0.10-0.30
- Slack agent per question: ~$0.01-0.05
- Monthly total (nightly + light Slack use): ~$10-20

---

## When something breaks

**Nightly run stops mid-way (50 deals analyzed, 30 skipped):** Individual deal failures are logged but should not halt the run. Check Actions log for exceptions. Common causes: CRM API rate limit (add sleep), call cache miss (re-run ETL), missing deal property (add to `etl.deal_properties` in `client.yaml`).

**HubSpot scores all zero:** Score extraction regex in `scripts/hubspot_deals.py` expects lines like `Metrics: 7/10` or `Champion: 8`. If prompt format drifts, scores won't parse. Check an analysis file in `output/` and confirm format matches regex in `_extract_scores_from_analysis()`.

**Slack agent returns "I don't have enough data to answer that":** Handler's Supabase query returned zero rows. Either table is empty (check ETL ran), filter is too strict (e.g., filtering for Q3 deals when it's Q1), or intent classification routed to wrong handler. Check Railway logs for SQL query, run it manually in Supabase.

**Waterfall empty after Week 2:** Waterfall (`scripts/analytics/compute_waterfall.py`) reads `deals_snapshot` rows across multiple weeks and requires `qualified_date` on each deal. If snapshots are missing, have null `fiscal_quarter` values, or deals lack `qualified_date`, waterfall will be empty. Confirm `scripts/analytics/snapshot_deals.py` wrote rows with non-null `fiscal_quarter`, `scripts/etl/seed_qualified_dates.py` populated `qualified_date` for all deals that reached qualified threshold, and `fiscal.fy_start_month` is set correctly in `client.yaml`. Note: waterfall needs TWO snapshots before it computes anything — first run correctly skips with "insufficient snapshot history."

**Factory raises "call_tools.primary = 'gongg' is not recognized":** Typo in config. Valid options: `fireflies`, `gong`, `apollo`. Factory uses Gap 2 discipline — no silent fallbacks. Fix typo in `config/client.yaml`.

---

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Both | Claude API (Sonnet 4.5 + Haiku 4.5) |
| `HUBSPOT_API_KEY` | Nightly | Private app token, deal read/write |
| `SUPABASE_URL` | Both | Project URL |
| `SUPABASE_SERVICE_KEY` | Both | service_role key (not anon) |
| `SUPABASE_DB_URL` | Migrations | Direct pooler connection string |
| `FIREFLIES_API_KEY` | Nightly | If `call_tools.primary: fireflies` |
| `GONG_ACCESS_KEY` / `GONG_ACCESS_KEY_SECRET` | Nightly | If `call_tools.primary: gong` |
| `APOLLO_API_KEY` | Nightly | If `call_tools.primary: apollo` |
| `GITHUB_TOKEN` / `GITHUB_REPO` | Nightly | Automatic in GitHub Actions |
| `ZAP_REPLY_URL` | Slack agent | Zapier catch hook for replies (treat as secret) |
| `SLACK_RELAY_SECRET` | Slack agent | Authenticates Zapier → Railway (optional but recommended) |
| `ADMIN_SECRET` | Slack agent | Guards `/admin/refresh-schema` |

---

## What's in `docs/`

Detailed guides that don't belong in the README:

- **`docs/adapter-guide.md`** — How to add a new call intelligence adapter (Fathom, Avoma, Chorus). `CallAdapter` interface, normalization rules, factory wiring.
- **`docs/data-schema.md`** — Supabase table contracts. Every table, every column, every index. What writes what, point-in-time semantics, historical backfill rules.
- **`scripts/migrations/README.md`** — Migration guide. Order matters (001–027), idempotency, verification fingerprints, rollback procedures.

Endpoint reference, file-by-file directory tour, step-by-step duplicates of skill instructions — all in `docs/`. If you're reading this five minutes before a demo, you don't need those. If you're debugging a specific issue or extending the system, you do.

---

Interested in forward deployment for your team? Reach out:

- Email: jeff@revopsimpact.us
- LinkedIn: [linkedin.com/in/jeffbethechange](https://linkedin.com/in/jeffbethechange)
