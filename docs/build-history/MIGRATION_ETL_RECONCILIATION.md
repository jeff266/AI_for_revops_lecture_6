# Migration and ETL Reconciliation

**Repo:** `jeff266/AI_for_revops_lecture_6` (template)
**Source:** `jeffignacio-growthbook/MEDDICC-agent` (read-only)

The template's migration sequence is internally inconsistent right now. Fixing
that comes before any further porting, because everything downstream reads what
these produce.

---

## What the audit found

**1. Migrations 028–042 are missing.** The template has 001–027, then jumps
straight to `043_add_call_scores.sql`. That fifteen-migration gap is the entire
forecast substrate and everything built on it:

- `deals_snapshot` point-in-time fields (`forecast_category`, `fiscal_quarter`,
  `week_of_quarter`)
- `call_transcripts` and the transcript metric columns
- the proposal lifecycle
- user personas, meetings, SDR tables
- the `fireflies_call_id` → `call_recording_id` rename
- the `backfill_confidence` vocabulary widening

So `043` sits on a schema missing everything it assumes.

**2. Migration 017 will reproduce a known production failure.** It defines:

```sql
backfill_confidence TEXT CHECK (backfill_confidence IN
  ('exact', 'interpolated', 'inferred', 'unknown', 'excluded_mismatch'))
```

That is the **old** vocabulary. The reconstruction code uses
`exact / pre_history / no_history`. In GrowthBook this produced
`23514 violates check constraint "deals_snapshot_backfill_confidence_check"`
— the write failed after the purge had already run, leaving the target quarters
empty. It was fixed by migration 039 widening the CHECK. The template has 017
and not 039, so it will fail in exactly the same place for exactly the same
reason.

**3. `etl_calls.py` references transcripts 33 times** against a `call_transcripts`
table that does not exist in the template's schema (migration 041).

---

## Step 1 — Reconcile the sequence

Go through GrowthBook's migrations 028–043 and sort each one:

| Disposition | Meaning |
|---|---|
| **Port as-is** | Generic schema the template needs |
| **Port with placeholders** | Structure travels, GrowthBook values do not |
| **Fold forward** | A later migration corrects an earlier one — merge rather than porting both |
| **Skip** | GrowthBook-specific, no template equivalent |

**Fold forward is the important one.** GrowthBook's history contains
corrections: 039 widens a CHECK that 017 got wrong; 035 renames a column 023
created. A template should not inherit a wrong constraint plus its later fix —
it should have the right constraint from the start.

Specifically:

- **017 + 039** → one migration with the correct vocabulary
  (`exact / pre_history / no_history`, keeping the old values for
  back-compatibility only if something reads them).
- **023 + 035** → the `call_recording_id` naming from the start, no rename.
- Check for other correction pairs in 028–043 and fold each.

**Renumber into a clean linear sequence.** No gaps, no duplicates. Include the
no-duplicate-number test from GrowthBook (`eval_migrations.py`) — it caught five
collision pairs there and will prevent the same drift here.

Report the mapping: old GrowthBook number → new template number → disposition.

---

## Step 2 — Make the sequence self-verifying

The template should not be able to reach the state it is in now.

- **No-duplicate-number test** — port from GrowthBook.
- **No-gap test** — the sequence must be contiguous. This is what would have
  caught 028–042 missing.
- **Vocabulary agreement test** — every CHECK constraint that encodes an enum
  must match the values the code writes. GrowthBook has this
  (`eval_check_vocabulary.py` or equivalent); it was written *after* the 23514
  failure. The template should have it before.
- **Applied-state check** — a script that reports which migrations are applied
  versus present, so "created" is never mistaken for "applied." That distinction
  cost a full debugging cycle in GrowthBook.

---

## Step 3 — Reconcile the ETLs

`etl_calls.py` and `etl_deals.py` exist in both repos and have diverged.

For each, diff template against GrowthBook and account for every difference:

**`etl_calls.py`** — GrowthBook's version has the fixes from this session:
- Fireflies transcript fetch (`get_transcript_sentences`), which the template's
  version does not do at all — it only pulls summaries
- Rate-limit backoff on GraphQL **body** errors, not just HTTP exceptions
  (Fireflies returns throttling in the response body; retry logic keyed on
  exceptions never fires)
- Source-priority dedup when a call appears in two sources
- The transcript persist path writing to `call_transcripts`

**`etl_deals.py`** — check for:
- point-in-time field population (`fiscal_quarter`, `week_of_quarter`)
- the inclusion rule: a deal belongs in a snapshot for date D only if it was
  created by D and had not reached a terminal stage before D
- whether it reads current state where it should read history

**The inclusion rule is the one to get right.** GrowthBook's snapshots
originally captured every deal regardless of lifecycle, so a deal closed months
earlier appeared in every later snapshot. That inflated one quarter's week-3
denominator from ~221 to 914 and produced a 14.96x coverage figure before anyone
noticed. The rule is small; its absence is not.

---

## Step 4 — Point-in-time correctness as a shipped invariant

Five of nine `deals_snapshot` fields in GrowthBook were originally written from
**current** state rather than as-of the snapshot date. Stage, value, close date,
owner, status. Every analysis reading them was wrong in a way that produced
plausible numbers rather than errors.

The template must ship with this correct and enforced:

- A module docstring on the snapshot writer stating the invariant plainly:
  *every field in `deals_snapshot` is the value as of `snapshot_date`, never
  current state.*
- The guard test that fails if the writer joins to the live deals table for any
  historical row.
- The strictly-backward-looking point-in-time helper (`get_field_at_date`) as
  the single implementation, with the fixture that proves it — including the
  backward-moving case (a deal regressing a stage) and the no-history case
  (returns null, never a default).

---

## Step 5 — Verification the client runs on their own data

This is what makes the template arrive at the standard rather than merely
containing the code.

Ship these as scripts a new client runs during onboarding, against their data:

**Coverage check** — what fraction of deals have calls, transcripts, scores.
GrowthBook's real answer was 26% snapshot coverage at one point, and the number
was invisible until measured.

**Determinism harness** — score one call five times, report the spread. A new
client learns their own jitter rather than inheriting an assumption.

**Reconciliation pattern** — for any analysis touching won/lost or counts,
capture before, compute after, refuse to commit if the numbers moved
unexplained.

**Plausibility assertions on every analytical output** — conversion above 100%,
coverage above 15x, a subset larger than its superset, parts not summing to a
whole. Cheap, deterministic, and they catch the class of failure that produces a
confident wrong number instead of a crash.

**CRM cross-check** — compare the agent's pipeline counts against what the
client sees in their CRM, and report the difference with its cause (close-date
filter, excluded stages, pipeline scope). GrowthBook's 78-versus-44 discrepancy
was a scope difference, not a bug — but nobody could tell until it was
reconciled explicitly.

---

## Sequence

1. **Step 1** — reconcile and renumber. Blocking; nothing else is safe until
   the sequence is coherent.
2. **Step 2** — the self-verifying tests, written immediately after so the
   sequence cannot drift again.
3. **Step 3 and 4** — ETL reconciliation and the point-in-time invariant,
   together, since the ETL is what writes the snapshot.
4. **Step 5** — the verification suite, last, wired into onboarding as the
   final step.

---

## The standard question

Porting the code gets a new client to *correct in the abstract*. What made
GrowthBook trustworthy was two days of finding that snapshots read current
state, the numerator was cumulative, the denominator carried stale pipeline, and
the evaluator was moving scores — none of which announced themselves.

Those specific findings do not transfer. The **machinery that found them** does:
reconciliation before commit, determinism characterization, plausibility
assertions, coverage measurement, refusing to proceed on thin data.

Step 5 is that machinery. It is the difference between shipping GrowthBook's
answers and shipping the ability to find a client's answers — and it is the only
version of "at that standard on day one" that is honest.
