---
name: revops-client-context
description: >
  Onboard a new client by building their competitive, product, and
  sales context. Use this skill when setting up a new deployment,
  calibrating the MEDDICC agent for a specific client, or updating
  context when the competitive landscape changes. Produces four files:
  config/context.yaml, config/client.yaml, prompts/CLAUDE.md, and
  prompts/evaluator_rubric.md. Triggers on: start client onboarding,
  set up context, configure the agent, calibrate for my client,
  update competitive context, who are our competitors, what are our
  objections.
---

# RevOps Client Context Onboarding

Build the context baseline that makes every intelligence layer accurate.
Read references/context-schema.md before starting.

Eight phases. Complete each before moving to the next.

## Phase 1 — Product and ICP

Ask one at a time:
1. "What does your product do in one sentence? Be specific."
2. "Who is your ICP? Company size, industry, and buyer title."
3. "What is your primary differentiator?"
4. "What qualification methodology do you use?"
5. "What CRM do you use? (HubSpot, Salesforce, other)"
6. "What call recording platform do you use? (Fireflies, Gong, other)"
7. "What does a good first call look like for your best reps?"
8. "What timezone is your sales team primarily in?
   (e.g. America/New_York, America/Los_Angeles, Europe/London)
   This ensures CRM dates match your team's calendar."

Push back on vague answers. Ask for real examples.

### Methodology Setup (based on Question 4 answer)

After they answer Question 4 about their qualification methodology:

**If MEDDICC:**
- Use existing prompts/CLAUDE.md template
- Use existing prompts/evaluator_rubric.md
- Components: Metrics, Economic Buyer, Decision Criteria, Decision Process, Identified Pain, Champion, Competition
- HubSpot properties: meddicc_score, meddicc_metrics_score, meddicc_economic_buyer_score, etc.

**If MEDDPIC:**
- Same as MEDDICC plus Process component
- Components: Metrics, Economic Buyer, Decision Criteria, Decision Process, Identified Pain, Champion, Competition, Process
- HubSpot properties: meddpic_score, meddpic_metrics_score, etc.

**If SPICED:**
- Generate SPICED-specific CLAUDE.md and evaluator_rubric.md
- Components: Situation, Pain, Impact, Critical Event, Decision
- HubSpot properties: spiced_score, spiced_situation_score, spiced_pain_score, spiced_impact_score, spiced_critical_event_score, spiced_decision_score

**If BANT:**
- Generate BANT-specific CLAUDE.md and evaluator_rubric.md
- Components: Budget, Authority, Need, Timeline
- HubSpot properties: bant_score, bant_budget_score, bant_authority_score, bant_need_score, bant_timeline_score

**If Custom:**
- Ask: "What are the components of your methodology? List them one by one."
- For each component, ask:
  - "What does {component} evaluate?"
  - "What does good {component} qualification look like?"
  - "What are common gaps or red flags for {component}?"
- Generate custom CLAUDE.md and evaluator_rubric.md from their answers
- HubSpot properties: custom_score, custom_{component_slug}_score

Store the methodology name and component list for Phase 8 config generation.

## Phase 2 — Call Tool Adapter Setup

After collecting the call tool name in Phase 1, run this:

If the tool is Fireflies or Gong:
  Tell user the adapter already exists.
  Skip to next phase.

If the tool is anything else (Fathom, Avoma, Chorus, etc.):

  STEP A: Research current API docs
  Use web search to find:
  - Base API URL for {tool}
  - Authentication method (Bearer, Basic, API Key header)
  - Endpoint to list recent calls/meetings
  - Endpoint to get transcript for a call ID
  - Endpoint to get summary/AI notes
  - Whether participant emails are returned
  - Rate limits

  STEP B: Generate the adapter

  If scripts/adapters/calls/base.py does not exist in this
  repo (older fork), create it first with exactly this
  interface, then proceed:

  ```python
  from abc import ABC, abstractmethod
  from typing import List, Optional
  from datetime import datetime

  class CallAdapter(ABC):
      """
      Contract for all call intelligence adapters.
      Every tool (Fireflies, Gong, Apollo, Fathom, Avoma...)
      implements exactly this interface. Method names are
      methodology-agnostic on purpose.
      """

      @abstractmethod
      def search_by_company(self, company_name: str,
                            since_date: Optional[datetime] = None
                            ) -> List[dict]:
          """Return call dicts for a company, newest data included."""

      @abstractmethod
      def format_summary(self, call: dict) -> str:
          """Format one call dict into an analysis-ready text
          summary. Must return >100 chars for real calls
          (Guard 3 in the nightly agent)."""

      @abstractmethod
      def get_meeting_attendees(self, call_id: str) -> List[dict]:
          """Return attendees with email where available:
          [{'name': ..., 'email': ...}, ...]. Return [] if the
          tool cannot provide attendees."""

      def test_connection(self) -> bool:
          """Optional override. Default: True."""
          return True
  ```

  Create scripts/adapters/calls/{tool_slug}.py following
  the interface in scripts/adapters/calls/base.py.

  Implement:
    search_by_company(company, since_date) -> list
    format_summary(call) -> str
    get_meeting_attendees(call_id) -> list

  STEP C: Simulate a test (no API key needed)

  Generate a mock API response that matches the tool's
  documented schema. Run the adapter methods against it.
  Print a validation report:

    ✓ search_by_company() — returns list of dicts
    ✓ format_summary_for_meddicc() — 847 chars (passes Guard 3)
    ✓ get_meeting_attendees() — returns email list
    ✓ No external domains leaked (internal domain filter works)
    ✓ Adapter conforms to CallAdapter interface

  If any check fails, fix the adapter before proceeding.

  STEP D: Commit the adapter

    git add scripts/adapters/calls/{tool_slug}.py
    git commit -m "Add {Tool} call adapter from onboarding"
    git push

  Tell user:
  "Adapter built and tested against mock data.
   To activate it: add your {Tool} API credentials
   to GitHub Secrets and run the calls ETL."

## Phase 3 — Competitive landscape

Ask them to name all competitors first, then go through each one:
- Full name as it appears in prospect conversations
- Type: direct / adjacent / internal_tool / status_quo
- What prospects say when they mention this competitor
- How the rep should respond
- When you win vs lose against them
- Any aliases (other names it appears as in transcripts)

Prompt: "Any internal tools? Any build-vs-buy situations?"

## Phase 4 — Objections

For each objection (collect at least 5):
1. "What are the actual words a prospect uses?"
2. "Which stage does this typically appear at?"
3. "What's the best rep response?"
4. "Category: switching cost / budget / timing / technical /
   internal politics / product gap / trust / other?"

Prompt: "What kills the most deals? What comes up earliest?"

## Phase 5 — Feature gaps and value metrics

Feature gaps — for each:
- The feature description
- Exact language prospects use when asking about it
- Roadmap item or genuine gap?

Value metrics:
"What quantifiable outcomes do champions use for the business case?"

## Phase 6 — HubSpot pipeline & analytics configuration

Tell the user to run: python scripts/discover_stages.py
Ask them to paste the output. It prints a suggested
pipeline.pipelines[] block (stage order, is_won / is_lost /
exclude_from_analysis hints, analyze: hints) — not a flat
exclusion list. Every hint in it was guessed from HubSpot's own
metadata or stage/pipeline labels and must be reviewed, not
trusted blindly.

Walk through the pasted output with them, resolving every HINT
and FILL IN marker:

1. Confirm order values reflect the true sales-cycle sequence
   for each pipeline (discover_stages.py numbers stages in
   HubSpot's own listing order, which is usually but not always
   correct).
2. Confirm is_won / is_lost / exclude_from_analysis per stage.
   Push back if a Disqualified-type stage is missing either
   flag — both are required together. A stage with only
   exclude_from_analysis looks "active forever" in analytics;
   it never resolves to won or lost.
3. Confirm exactly one pipeline has is_primary: true, and which
   pipelines (if any) should get analyze: false. Reminder:
   analyze: false excludes a pipeline from MEDDICC/SPICED
   analysis but still includes it in analytics (won totals,
   retention, snapshots) — it is not a full exclusion.
4. Ask: "Which stage order counts as 'qualified' for each
   pipeline?" This is where the sales-cycle clock starts, and
   what the win-rate denominator requires a deal to have
   reached. → qualified_stage_order per pipeline.

Then ask the optional capability-surface questions. All of these
default to unset/off — only write a key if the client actually
answers; today's behavior (value_field: amount, no SAO field,
calendar fiscal year) is what an unanswered question preserves:

5. "What HubSpot property holds deal value?" Default: amount.
   If they track New ARR and Expansion ARR as separate
   properties instead of one combined field, offer the computed
   option:
     value_field:
       type: computed
       components: ["<new arr property>", "<expansion arr property>"]
   Warn explicitly: HubSpot property NAMES in the API (internal
   names) often differ from the LABELS shown in the HubSpot UI —
   confirm the real internal name via GET /crm/v3/properties/deals,
   never guess it from the label.
6. "Do you have an SAO-style qualification field — a boolean
   property marking a deal as Sales Accepted?" If yes, capture
   its internal property name as win_rate_qualified_field. If
   no, leave unset — win rate then falls back to
   highest_stage_order_reached >= qualified_stage_order.
7. Lost-reason field: query HubSpot's deal properties (GET
   /crm/v3/properties/deals) for property names containing both
   "lost" and "reason". Show the candidates found and confirm
   which one to use for pipeline.lost_reason_field (HubSpot's
   default is closed_lost_reason — confirm the portal actually
   has it before assuming).
8. "What month does your fiscal year start?" 1 = January /
   calendar year, the default — only probe further if they say
   their fiscal year isn't calendar-aligned. → fiscal.fy_start_month.
9. "What day should the weekly analytics snapshot run?" Default
   is Sunday 3am UTC, matching .github/workflows/weekly-analytics.yml
   as shipped. If they want a different day/time, edit that
   workflow's cron line directly — GitHub Actions schedules are
   static in the workflow file, not read from client.yaml.

Show the fully-resolved pipeline: block back to them and confirm
before writing anything.

## Phase 7 — Learning preferences

1. "How many companies must show a pattern before it becomes
   a permanent instruction? (default: 2)"
2. "Any instructions that should never be auto-removed?"
3. "Who reviews the learning PRs?"

## Phase 8 — Generate and deploy config files

Read all four reference files before generating anything.

Generate all four files fully populated from the interview.
No placeholder text anywhere.

When generating prompts and rubric, resolve every {{if methodology
...}} conditional against the components of the selected methodology
— never leave conditional markers in output.

### If running in Claude Code (has file system access):

Write files directly — do not show as code blocks:

1. Write config/context.yaml
2. Write config/client.yaml with:
   - The full pipeline: block resolved in Phase 6 — real stage
     IDs, order values, is_won / is_lost / exclude_from_analysis,
     is_primary, analyze:, and qualified_stage_order for every
     pipeline. No placeholder stage IDs — Phase 6 already
     resolved real ones.
   - Any optional capability-surface fields the client answered
     in Phase 6 (value_field, win_rate_qualified_field,
     lost_reason_field, fiscal.fy_start_month) written live;
     leave everything they didn't answer commented/unset —
     do not invent values.
   - call_tools.primary set to the adapter slug from Phase 2
     (fireflies, gong, or custom tool slug)
   - methodology: {methodology_name}
   - hubspot.properties.score: {methodology_slug}_score
   - hubspot.properties.component_scores: map each component to
     {methodology_slug}_{component_slug}_score
3. Write prompts/CLAUDE.md (methodology-specific from Phase 1)
4. Write prompts/evaluator_rubric.md (methodology-specific from Phase 1)

If the client wants a non-default weekly analytics snapshot day
(Phase 6, question 9), update the cron line in
.github/workflows/weekly-analytics.yml to match.

Commit everything:
  git add config/ prompts/
  git commit -m "Add [company] client context and config"
  git push

Then run the HubSpot property setup:
  python scripts/setup_hubspot_properties.py

This will create the {methodology} score properties in HubSpot
by reading the property names from config/client.yaml.

Tell the student: "Done. Config is live in the repo.
HubSpot properties created for {methodology}.
Next step: add GitHub Secrets, then run the ETL."

### If running in Claude.ai (no file system access):

Present each file as a labeled code block:

**config/context.yaml** — copy this to your repo
[content]

**config/client.yaml** — copy this to your repo
(with call_tools.primary set to {adapter_slug},
 methodology and HubSpot properties for {methodology})
[content]

**prompts/CLAUDE.md** — copy this to your repo
[content]

**prompts/evaluator_rubric.md** — copy this to your repo
[content]

Then show the deployment checklist:
□ Copy all four files into your forked repo
□ Run: python scripts/discover_stages.py
□ Update the pipeline: block in config/client.yaml with your
  real HubSpot pipeline/stage IDs, order, is_won/is_lost/
  exclude_from_analysis flags, and qualified_stage_order
  (see Phase 6)
□ git add config/ prompts/ && git commit -m "Add client context"
□ git push
