# RevOps MEDDICC Agent — Production Status

**Template Version:** 2026-08-25
**Repository:** AI_for_revops_lecture_6

This template is a production-ready MEDDICC agent for RevOps teams. It was
ported from a live the reference deployment deployment, scrubbed of all client-specific
data, and made generic for any HubSpot/Salesforce user running MEDDICC,
MEDDPICC, SPICED, or BANT.

---

## What Works

The **nightly MEDDICC agent** is complete and tested:

- ETL: Pull deals from HubSpot → `memory/deals/index.json`
- ETL: Pull calls from Fireflies/Gong → `memory/calls/*.json` cache
- Context builder: Haiku synthesizes cumulative MEDDICC state from call cache
- Generator/Evaluator/Reflection loop: Sonnet scores, Haiku evaluates,
  Haiku reflection gate decides if a learning is worth keeping
- HubSpot write-back: 6 MEDDICC component scores + overall score written
  to HubSpot deal properties
- Supabase write: Parallel write to `analyses` table
- Self-improvement: Learnings extracted → synthesizer → PR to `prompts/CLAUDE.md`
- Token tracking: Every LLM call logged with role, tokens, cost
- GitHub Actions: Scheduled nightly and weekly runs

The **CRO Slack agent** (query layer) is complete and runs on Railway:

- Intent classification: Precomputed handler vs dynamic query path
- 16 precomputed handlers: at-risk deals, pipeline coverage, objections,
  feature gaps, deal deep-dives, rubric coaching, win/loss intelligence
- Dynamic query path: Novel combinations via typed query primitives
- Thread context: Follow-ups reuse deals from prior messages
- Self-assessment: Correctness + tone check before reply, retry if needed
- Zapier relay: Inbound (Slack → Railway) + outbound (Railway → Slack)

The **weekly analytics** pass runs Sunday 3am UTC:

- Pipeline snapshots (`scripts/analytics/snapshot_deals.py`)
- Forecast computation (stage-weighted + category-weighted)
- Deal status tracking (won/lost/moved)
- Waterfall computation (`scripts/analytics/compute_waterfall.py`): Stage-to-stage
  movement tracking with null-propagation (unknown deal values excluded from
  dollar sums, not zero-filled) and point-in-time qualification (uses
  qualified_date immutable event timestamp, not highest_stage_order_reached
  current-state high-water mark)
- Win/loss narratives (`scripts/analytics/generate_win_loss.py`): Three-outcome
  classification (won/lost/slipped — a deal that closed in a later quarter than
  committed is slipped, not lost), point-in-time semantics reading from
  deals_snapshot for historical progression, min_evidence_count gate (below
  threshold returns null with reason rather than fabricating narrative from
  thin material)
- Segment analysis: Embedded in `scripts/analytics/compute_pipeline_generation.py`.
  Per-segment pipeline generation, cycle-time expectations from
  config.segmentation.bands, segment field on deal responses. Note: segment-specific
  win rates, conversion rates, and velocity aren't isolated from pipeline generation
  in this version (genuine gap — not a missing file, but a missing capability)

The **call adapter layer** supports multi-source transcript ingestion:

- Factory (`scripts/adapters/calls/__init__.py`): get_call_adapter(config) reads
  call_tools.primary and instantiates the matching adapter (fireflies, gong, apollo)
- Three adapters: FirefliesClient, GongAdapter, ApolloClient — all implement
  CallAdapter interface
- Transcript normalization (`scripts/transcript_store.py`): Units converted at
  boundary (Fireflies seconds, Apollo milliseconds, Gong no-timestamps), speaker-attributed,
  consumers never know source
- Gong limitation documented: API provides no timing data, so talk-time and
  longest-monologue metrics unavailable for Gong transcripts (question count works)

The **verification suite** is complete:

- 87 passing tests across `scripts/test_*.py`
- CRM crosscheck (agent count vs HubSpot count reconciliation)
- Config validation (raises on missing critical keys)
- Name guard (no client names in tracked code)

---

## What Is Not Built

**Nothing.** All analytics scripts documented in earlier STATUS.md versions have
been ported, were never real (incorrectly inferred from config presence), or were
capabilities embedded in other files rather than standalone scripts.

Of six original "not built" entries:
- compute_waterfall.py: ported (560 lines, null-propagation + point-in-time qualification)
- generate_win_loss.py: ported (358 lines, three-outcome classification)
- compute_segment_metrics.py: never existed (segment analysis embedded in compute_pipeline_generation.py)
- Gong adapter factory: ported (factory wiring + transcript normalization)
- Gong adapter implementation: already existed (525 lines, fully implemented)
- Shape-aware synthesis: never existed in reference deployment (see Known Limitations below)

Porting is complete. What remains are **known limitations** (design gaps shared by
both implementations) and **untested-against-live-data** calibrations (thresholds
that may need client-specific tuning).

---

## Known Limitations

These are design gaps present in **both** the reference deployment and this template.
They are not porting gaps — they reflect capabilities that were never built in either
codebase.

### Shape Validation (Hallucination Prevention)

**Gap:** Neither the reference deployment nor this template validates that a synthesized
answer's structure matches the handler's data.

**What this means:** A CRO Slack agent response can assert "Deal X has strong champion
evidence (score 8)" when the handler returned a champion score of 3. The synthesis can
drift from the data it was given.

**What is checked:** Correctness (did the answer address the question? right data source?
gaps acknowledged?) and tone (executive vs operational voice). Both are assessed via
`api/assessor.py`.

**What is NOT checked:** Whether the response's assertions match the actual values in the
handler's query results. A response can claim a number, trend, or state that doesn't
appear in the underlying rows.

**Workaround:** The correctness check catches some shape drift (e.g., answering "what deals
did we win?" with waterfall totals instead of individual won deals), but it does not validate
field-level accuracy. A client may see occasional hallucinations where a synthesized insight
contradicts the data. These are rare but not prevented.

**Why it's here:** This was listed in earlier STATUS.md versions as "not ported from the
reference deployment," implying the reference had it and the template didn't. Investigation
(grep of reference `api/assessor.py` and `api/router.py`) confirmed the capability never
existed. Router comments mention "shape" as a concept, but no validation logic was implemented.

This is a known gap in both implementations, not a porting gap.

---

## What Is Untested and What Is Provisional

### Untested Against Live Data

This template has **never run against live client data**. It was ported
from a working the reference deployment deployment, but the port rewrote every
client-specific reference (stage IDs, pipeline names, competitor names,
internal domains) to be config-driven. The following are true:

- The test suite passes (87 passing tests).
- Every file reads from `config/client.yaml` and `config/context.yaml`
  instead of hardcoding values.
- The name guard confirms no client names remain in tracked code.
- The reference the reference deployment deployment runs every night without error.

But **no one has deployed this template to a fresh client and watched it
run a full nightly cycle**. Edge cases may exist where a config key is
read but not validated, or where a HubSpot API response shape differs
from what the reference deployment sees.

### Provisional Thresholds (Guesses, Not Measurements)

The following values in `config/client.yaml` are **guesses**. They came
from the reference deployment, but they were calibrated to the reference deployment's
sales motion and may not generalize:

**`quality_thresholds.minimum_quality_score: 70`**
Determines when the evaluator rejects a generated analysis as too weak.
the reference deployment's live data showed that scores below 70 correlated with vague
or hedging language. A team with shorter calls or less structured
discovery might need to lower this; a team with deep enterprise cycles
might raise it.

**`stage_progression` thresholds (e.g., `identified_pain: 5`, `champion: 4`)**
These are the MEDDICC component scores required to move from one stage
to the next. They shape the agent's risk warnings ("this deal is in
Scoping but champion is only a 3 — below the 4 threshold"). the reference deployment's
thresholds reflect their qualification bar. Your team's bar may differ.

**`deal_health.strong.minimum_components_above_6: 5`**
Defines when a deal is flagged as "strong" in the at-risk handler. Five
components above 6 worked for the reference deployment. A team with a lighter
qualification methodology (BANT instead of MEDDICC) might need fewer.

**`api/assessor.py` correctness floor (0.30)**
The Slack agent self-assesses answer correctness on a 0-1 scale and
retries if it falls below 0.30. This threshold was chosen arbitrarily —
it has not been tuned against real Slack question volume. A client might
find 0.30 too permissive (too many weak answers get through) or too
strict (too many retries on acceptable answers).

---

## Recommendations for First Deployment

1. **Run `discover_stages.py` and confirm every stage's classification.**
   The onboarding skill generates a pipeline block with HINT annotations.
   Walk through each stage and confirm `is_won`, `is_lost`,
   `exclude_from_analysis`, and `qualified_stage_order`. A wrong
   classification corrupts the waterfall and win-rate calculations.

2. **Set a test deal and watch the first nightly run.**
   Create a single test deal in HubSpot, attach a Fireflies call, and
   trigger the nightly workflow manually. Confirm the scores get written
   back, the Supabase row appears, and no errors surface in the Actions log.

3. **Check the snapshot coverage after the first Sunday.**
   The weekly analytics writes a snapshot every Sunday 3am UTC. After the
   first run, query `deals_snapshot` and confirm the row count matches
   your active pipeline size. If it's capped at ~291 or drops deals with
   null stages, the point-in-time reconstruction has a bug (this was fixed
   in the reference deployment but may reappear under different HubSpot
   property-history shapes).

4. **Lower the correctness floor if the Slack agent retries too often.**
   If the Slack agent logs show excessive retries on reasonable-looking
   answers, lower `ASSESS_CORRECTNESS_FLOOR` in `api/assessor.py` from
   0.30 to 0.20. If it passes weak answers that miss the user's question,
   raise it to 0.40.

5. **Calibrate stage_progression thresholds after 2-3 weeks.**
   Watch the nightly analysis outputs. If the agent flags too many deals
   as "below threshold for this stage," your thresholds are too strict.
   If it never warns and a rep later says "I knew that deal was weak,"
   your thresholds are too loose. Adjust the `stage_progression` block
   in `config/client.yaml` and re-run.

---

## What to Do If Something Breaks

**The nightly run stops mid-way (50 deals analyzed, 30 skipped):**
Individual deal failures are logged but should not halt the run. Check
the Actions log for exceptions. Common causes: HubSpot API rate limit
(add a sleep), Fireflies call cache miss (re-run ETL), missing deal
property (add it to `etl.deal_properties` in `client.yaml`).

**HubSpot scores are all zero:**
The score extraction regex in `scripts/hubspot_deals.py` expects lines
like `Metrics: 7/10` or `Champion: 8`. If your prompt format drifts,
scores won't parse. Check an analysis file in `output/` and confirm the
format matches the regex in `_extract_scores_from_analysis()`.

**Slack agent returns "I don't have enough data to answer that":**
The handler's Supabase query returned zero rows. Either the table is
empty (check ETL ran), the filter is too strict (e.g., filtering for Q3
deals when it's Q1), or the intent classification routed to the wrong
handler. Check the Railway logs for the SQL query and run it manually in
Supabase to see what it returns.

**The waterfall is empty after Week 2:**
The waterfall (`scripts/analytics/compute_waterfall.py`) reads `deals_snapshot`
rows across multiple weeks and requires qualified_date on each deal. If
snapshots are missing, have null `fiscal_quarter` values, or deals lack
qualified_date, the waterfall will be empty. Confirm `scripts/analytics/snapshot_deals.py`
wrote rows with non-null `fiscal_quarter`, `scripts/etl/seed_qualified_dates.py`
populated qualified_date for all deals that reached the qualified threshold,
and that `fiscal.fy_start_month` is set correctly in `client.yaml`. Note: The
waterfall needs TWO snapshots before it computes anything — first run correctly
skips with "insufficient snapshot history."

---

## Final Notes

This template is **production-ready in structure** but **untested in the wild**.
The code is clean, the tests pass, and the reference deployment proves the
architecture works. But every client has a different HubSpot shape, a
different call cadence, and a different qualification bar. Expect to spend
2-3 weeks calibrating thresholds and watching the first few nightly runs
before trusting it as a source of truth.

All documented capabilities have been ported. The nightly agent scores deals and
writes them back; the Slack agent answers pipeline questions; the weekly snapshots
and waterfall build a time-series record; win/loss narratives extract coaching insight
from closed deals; the call adapter layer supports Fireflies, Gong, and Apollo.

Known limitations (shape validation, provisional thresholds) are documented above.
These are design gaps shared by both the reference deployment and this template, not
porting gaps.

If you deploy this and hit an edge case, document it. This template improves
as more teams run it and report what broke. That is how the reference
deployment got stable, and it is how this one will too.
