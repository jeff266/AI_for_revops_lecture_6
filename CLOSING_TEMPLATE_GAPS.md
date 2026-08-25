# Closing the Template Gaps

Written from a review of `jeff266/AI_for_revops_lecture_6` at `bac8b56` against
seven criteria: onboarding ease, config-driven code, call adapter universality,
stage config, sales process config, objections, and MEDDICC tailored to stage
and motion.

Ordered by what unblocks what, not by size.

---

## What already works — do not touch

**Stage configuration is the strongest part of this template.**
`discover_stages.py` generates from the live CRM, `stage_id_mapping.yaml`
handles retired stages, `field_semantics.yaml` maps IDs to semantic buckets,
transitions are keyed on funnel position rather than client labels, and the
N-stages-equals-N-transitions rule is now correct. Nothing to fix.

**The onboarding interview design is good.** One question at a time, pushes back
on vague answers, explains why each answer matters. The questions are right —
only their consumption needs work.

**All three call adapters exist** — `fireflies.py`, `gong.py`, `apollo.py` — with
a factory and a clear error telling you how to add a fourth.

---

## Gap 1 — The methodology key bug (blocking)

`utils.py` defines `'MEDDPIC'` (one C). `client.yaml` documents `MEDDPICC` (two).
A client following the documented option gets a failed lookup that **silently
falls back to MEDDICC** and returns seven components while the config says eight.

Fix: rename the dict key to `MEDDPICC` — that is the correct spelling (Metrics,
Economic Buyer, Decision Criteria, Decision Process, Paper Process, Identified
Pain, Champion, Competition). Check `MEDDPIC` is not referenced elsewhere first.

**The more important half:** make the fallback loud. `get_components()` currently
defaults on an unrecognized key. It should raise, naming the value it got and
listing the valid options. This exact failure shape — config that looks set but
is not honored, failing silently rather than erroring — has now appeared three
times in this template (the methodology key, the transition off-by-one, the
missing `.forbidden_names.example`).

This gates Phase 4b's acceptance test, so it comes first.

---

## Gap 2 — Nothing validates a finished onboarding

A client completes both skills and has no way to know the config is coherent
until something fails at runtime. Every gap in this document would have been
caught by a validator.

Build `scripts/validate_config.py`, run as the last step of
`revops-agent-setup`:

- `sales_methodology` resolves to a known methodology (catches Gap 1)
- `stage_progression` transition count equals the open-stage count
- Every component referenced in `stage_progression` exists in the selected
  methodology
- Required credentials present and non-placeholder
- CRM adapter connects; call adapter connects
- `field_semantics.yaml` is populated, not still the placeholder
- Each `YOUR_*` placeholder still present is reported as unfinished

Output a pass/fail list, not a single boolean. A new client should be able to
run this and see exactly what is left.

---

## Gap 3 — Call config is single-source

`call_tools.primary` selects one adapter. GrowthBook runs Fireflies **and**
Apollo together — a recorder plus a dialer — with priority-based dedup when both
have the same call.

That is a common real setup and the template cannot express it.

Port the `call_sources` block:

```yaml
call_sources:
  primary: fireflies      # the recorder — rich transcripts
  dialer: apollo          # optional — dialer with weaker summaries
  priority: [fireflies, apollo]   # dedup order, best transcript first
```

And `get_call_sources()` returning a list in priority order, with
`deduplicate_calls_by_source_priority()`. Keep `get_call_adapter()` working for
single-source clients — most will only have one.

Belongs in Phase 4c alongside the substrate port.

---

## Gap 4 — Objections are a placeholder, not a system

`coaching_client.yaml` has a commented-out `objections` list. A client fills it
in and nothing consumes it.

GrowthBook has the working version: `objection_categories` (the client's actual
objection types) plus `objection_category_to_blocker` mapping each to the
universal blocker taxonomy in `coaching_seed.yaml` — technical, resourcing,
cultural, commercial — each with a prescribed response.

That split is the right one: the categories are client-specific, the taxonomy
and responses are universal. Port both halves and wire the consumption, so an
objection surfaced on a call maps to a blocker type with a response rather than
sitting in a config nothing reads.

---

## Gap 5 — Motion is never captured

Nothing in the config records whether this is an SE+AE motion, a single-rep
motion, or founder-led. This already caused a problem: the coaching seed's
prescribed responses assumed an SE/AE split ("hand to the AE", "not the SE's to
negotiate") and had to be de-roled generically.

De-roling was the right immediate fix, but the information is genuinely useful
and should be captured rather than avoided.

Add one onboarding question and one config key:

```yaml
organization:
  sales_motion: "se_ae"   # se_ae | single_rep | founder_led
```

Then the blocker responses can be motion-aware again — a two-role motion gets
"hand to the AE," a single-rep motion gets "bring in pricing authority," and
neither is wrong for the other.

---

## Gap 6 — MEDDICC is not tailored to stage

This is the largest remaining gap and the one with the clearest prior art.

`stage_progression` gates vary by stage, which is real. But **the scoring prompt
does not.** A discovery call and a commercial call are scored against the same
expectations.

That is wrong in a specific, known way: decision process at 3 after one
discovery call is normal; at 3 after a commercial call it is a gap. Same number,
opposite meaning. Scoring absolute rather than stage-relative means the rubric
grades the call type rather than the deal.

GrowthBook has `stage_focus_questions` — per-stage, per-component prompts that
adapt what the scorer looks for by deal maturity. It has not been ported.

Two parts:

1. Port `stage_focus_questions` into `coaching_client.yaml` as placeholdered
   structure, with the onboarding skill populating it.
2. Have the scorer read the deal's stage bucket and apply the matching
   expectations.

**Caution, learned the hard way:** stage must not enter the *scoring* prompt as
a raw value. Stage is frequently stale, and conditioning a score on a stale
stage produces a wrong score — and it forecloses the stage-vs-score comparison
that detects stale CRM data in the first place. Stage-relative *expectations*
applied at the reporting and gap-analysis layer is the right shape; stage as a
scoring input is not.

---

## Sequence

1. **Gap 1** — one-line rename plus a loud failure. Unblocks 4b's acceptance
   test, which gates the rest of Phase 4.
2. **Phase 4c/4d** as planned, with **Gap 3** folded in (multi-source call
   config ports alongside the substrate).
3. **Gap 4 and Gap 5** — objections consumption and motion capture. Both are
   config plus onboarding questions, small and independent.
4. **Gap 6** — stage-tailored scoring. Largest, and it should come after the
   progressive scorer is ported and its acceptance test passes, since it changes
   what the scorer reads.
5. **Gap 2** — the validator, built last so it can check everything above, then
   run as the final onboarding step.
6. **Phase 6** — stand up a fictional client end to end. MEDDPICC, three open
   stages, a name that is not GrowthBook. If it needs Python edited, something
   above is incomplete.

---

## The pattern worth naming

Three of these gaps share a shape: **config that appears set but is not
honored, failing silently rather than erroring.** The methodology key falls back
to a default. The transition count was off by one and the final gate returned
empty. `.forbidden_names` was read but never shipped as an example.

None crashed. All would have produced plausible wrong behavior in a new client's
deployment, discovered weeks later if at all.

The validator in Gap 2 is the systemic answer, and it is worth treating as more
than a checklist item — it is the thing that makes every other config decision
in this template verifiable at onboarding time rather than at failure time.
