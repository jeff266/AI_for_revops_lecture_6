# RevOps MEDDICC Agent

Your sales calls contain the truth about every deal's health, but that
truth usually dies in a rep's head or a forgotten call recording. This
repo turns those calls into an always-current, honestly-scored pipeline
that your whole team can see and question in plain language.

It is two systems that share one database:

1. **The nightly agent** re-scores your full active pipeline against
   your qualification methodology every night and writes the scores
   back to HubSpot. It runs on GitHub Actions. No server to babysit.
2. **The CRO Slack agent** lets anyone ask the pipeline questions in
   Slack ("which deals are at risk?", "show me the Acme deal", "what's
   our Q3 coverage?") and get a grounded answer in seconds. It runs as
   a small FastAPI service on Railway.

You can run the nightly agent alone. The Slack agent is optional and
sits on top of the same Supabase data the nightly agent produces.

---

Interested in forward deployment for your team? Reach out:

- Email: jeff@revopsimpact.us
- LinkedIn: [linkedin.com/in/jeffbethechange](https://linkedin.com/in/jeffbethechange)

---

## The whole system at a glance

```
                        ┌─────────────────────────────┐
   Call platform ──────▶│  Nightly agent (GitHub       │
   (Fireflies/Gong)     │  Actions)                    │
                        │  ETL → score → write back    │
   HubSpot ────────────▶│                              │
        ▲               └───────────┬─────────────────┘
        │ MEDDICC scores            │ analyses, deals,
        │ written back              │ waterfall, objections,
        │                           ▼ feature gaps
        │               ┌─────────────────────────────┐
        └───────────────│  Supabase (source of truth   │
                        │  for the query layer)        │
                        └───────────┬─────────────────┘
                                    │
   Slack ──▶ Zapier ──▶ Railway ────┘  reads, synthesizes,
     ▲                  (FastAPI +      replies
     └── Zapier ◀────── Claude)
```

The nightly agent is the writer. Supabase is the shared record. The
Slack agent is the reader. Everything the Slack agent answers was
produced by the nightly and weekly jobs.

---

## Part 1 — The nightly agent

Each night it re-evaluates your full active pipeline. It pulls the
latest call transcripts, scores every deal on MEDDICC (or MEDDPICC,
SPICED, or BANT, configurable to how your team actually sells), and
writes the scores straight back to HubSpot so reps and managers see
the same picture. It flags risk before it becomes a surprise in the
forecast call, and it gets sharper over time as it learns your team's
patterns.

Beyond nightly scoring, it runs a weekly analytics pass across the
whole pipeline:

- **Waterfall tracking**: see exactly where deals are moving forward,
  sliding back, or dying, stage by stage
- **Win/loss narratives**: automatically extracted from call evidence,
  not just the close reason field
- **Objection log**: a searchable record of what prospects actually
  pushed back on
- **Feature-gap backlog**: requested features pulled straight from
  calls, ranked by how often and how severely they come up

### What runs automatically

| Time (UTC) | Job | What it does |
|---|---|---|
| 1:00 AM | Daily Deal ETL | Updates active deal index from HubSpot |
| 1:30 AM | Daily Calls ETL | Fetches new calls for active deals |
| 2:00 AM | MEDDICC Agent | Analyzes deals, writes to HubSpot + Supabase |
| Sun 3:00 AM | Weekly Analytics | Waterfall, win/loss, objections, feature gaps |

### What runs nightly

```
2am UTC: GitHub Actions fires
  → Load active deals from deal index
  → For each deal: load call cache → context builder (Haiku)
  → Generator (Sonnet) → Evaluator (Haiku) → Reflection gate
  → Write analysis to GitHub output/
  → Write 6 MEDDICC scores to HubSpot deal properties
  → Write analysis to Supabase for the query layer
  → Update CLAUDE.md via PR if new patterns emerge
```

---

## Part 2 — The CRO Slack agent

Message the bot in Slack. Zapier catches the message and posts it to
the Railway service. The service classifies the question, pulls the
relevant rows from Supabase, has Claude synthesize an answer, checks
its own answer for correctness and tone, and sends the reply back
through Zapier into the Slack thread. Follow-ups in the same thread
keep context, so "who owns those?" resolves against the deals from the
previous answer.

### What it can answer

**Precomputed handlers (fast path)**
```
what is our pipeline this quarter?
which deals are at risk?
show me ARR by customer
what are our top objections this quarter?
what feature gaps are blockers?
what's our pipeline coverage this quarter?
```

**Dynamic query path (novel combinations)**
```
which deals have a champion score above 6 and close in Q3?
which rep has created the most pipeline value this quarter?
which companies have both a budget objection and a feature gap?
which deals are in Technical Evaluation with no economic buyer confirmed?
show me deals where pain is identified but metrics aren't
```

**Deal deep-dives**
```
show me the Acme deal
what's the status on Contoso?
which of our open deals have the strongest decision process?
```

**Rubric and coaching**
```
what does a 6 mean for champion?
how do I improve a metrics score?
what separates a 7 from a 9 on decision process?
```

**Win/loss intelligence**
```
why did we lose our last three deals?
what competitors keep coming up in lost deals?
which objections are showing up most in Technical Evaluation?
```

**Coverage and targets** (once you set targets)
```
set AE team Q3 target $2M
what's our Q3 coverage?
which rep is furthest from their number?
```

**Thread follow-ups** (test these as sequences)
```
which deals close in September?
[reply] who owns those?
[reply] which of those are at risk?
```

### How a question flows

```
Slack message
  → Zapier catch hook → POST /slack/question (Railway/FastAPI)
  → entity-scope check (reuse deals already in this thread?)
  → intent classification → precomputed handler OR dynamic query
  → pull rows from Supabase
  → synthesize answer (Sonnet)
  → self-assess correctness + tone, retry if needed (Haiku)
  → POST answer to ZAP_REPLY_URL → Zapier → Slack thread
  → cache result + save thread entities for follow-ups
```

### Service endpoints (`api/main.py`)

| Method | Route | Purpose |
|---|---|---|
| POST | `/slack/question` | Receives a question from Zapier, replies async |
| GET | `/health` | Health check for Railway |
| POST | `/admin/refresh-schema` | Clears the schema cache (needs `ADMIN_SECRET`) |

**Railway start command:**
```
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

---

## Setup

### Step 1 · Credentials and context

Open this repo in Claude Code. On a fresh fork it detects the missing
config files and walks you through setup. Just say: **"set up this repo"**
then **"start client onboarding"**.

Two skills drive this (see `skills/`):

- `revops-agent-setup` collects every credential one at a time and
  writes your `.env` plus a GitHub Secrets checklist.
- `revops-client-context` interviews you about your product,
  competitors, objections, and pipeline, then writes `config/client.yaml`,
  `config/context.yaml`, `prompts/CLAUDE.md`, and
  `prompts/evaluator_rubric.md` — and generates a call-tool adapter if
  you use something other than Fireflies or Gong.

In **Claude.ai** (web/mobile), paste each `SKILL.md` into the custom
skill creator, then say "start client onboarding" or "set up credentials."

### Step 2 · Database

Run the Supabase migrations (001–027) to build the schema:

```bash
python scripts/setup_supabase.py
```

Migrations 001–017 cover the nightly agent and analytics. Migrations
018–027 add the CRO agent tables (conversation threads, result cache,
entity registry, learning log, sales signals). See
`scripts/migrations/README.md`.

### Step 3 · GitHub Secrets (nightly agent)

After the setup skill writes your `.env`, add the values as GitHub
Secrets under the **Agent** environment:

```bash
gh secret set --env Agent --env-file .env
```

### Step 4 · First nightly run

Go to **Actions → MEDDICC Agent Nightly Run → Run workflow**. The first
run analyzes your full active pipeline. After that it runs every night.

### Step 5 · Deploy the Slack agent (optional)

Only needed if you want the Slack Q&A layer.

1. Deploy this repo to Railway. Start command:
   `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
2. Set the Railway environment variables (see the table below).
3. In Zapier, build two Zaps:
   - **Inbound:** Slack trigger (message / mention) → POST to your
     Railway `/slack/question` with the message text, user, channel,
     and thread_ts.
   - **Outbound:** Catch hook that receives the agent's reply and posts
     it back to the Slack thread. Put that catch hook's URL in
     `ZAP_REPLY_URL`.
4. Message the bot in Slack and confirm you get a threaded reply.

> **Security note:** the Zapier catch-hook URL is an unauthenticated
> write path into your Slack replies. Treat it as a secret, and
> validate the Slack signing secret on the inbound Zap so the endpoint
> can't be replayed by a third party.

---

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | both | Claude API |
| `HUBSPOT_API_KEY` | nightly | Private app token, deal read/write |
| `SUPABASE_URL` | both | Project URL |
| `SUPABASE_SERVICE_KEY` | both | service_role key (not anon) |
| `SUPABASE_DB_URL` | migrations | Direct pooler connection string |
| `FIREFLIES_API_KEY` | nightly | If using Fireflies |
| `GONG_ACCESS_KEY` / `GONG_ACCESS_KEY_SECRET` | nightly | If using Gong |
| `APOLLO_API_KEY` | enrichment | Participant enrichment (optional) |
| `GITHUB_TOKEN` / `GITHUB_REPO` | nightly | Automatic in Actions |
| `ZAP_REPLY_URL` | Slack agent | Zapier catch hook for replies |
| `ADMIN_SECRET` | Slack agent | Guards `/admin/refresh-schema` |

---

## Call intelligence platforms

The agent ships with adapters for two platforms and a documented
interface for adding more.

**Fireflies** (default): simple API key. Set `call_tools.primary: "fireflies"`.

**Gong**: Access Key + Secret, richer structured data. Set
`call_tools.primary: "gong"`.

**Anything else** (Fathom, Avoma, Chorus): the client-context skill
web-searches the tool's API docs and generates an adapter against the
`CallAdapter` interface in `scripts/adapters/calls/base.py`. See
`docs/adapter-guide.md`.

---

## Configuration

Two files hold everything client-specific. The onboarding skill writes
both; you rarely edit them by hand.

**`config/client.yaml`** — how your pipeline is shaped:
`organization` (name, internal domains), `fiscal` (year start),
`segmentation` (size bands and cycle lengths), `pipeline` and
`stage_progression` (your HubSpot stage IDs and order),
`quality_thresholds`, `deal_health`, `models`, `call_tools`, `etl`.

**`config/context.yaml`** — what your team sells against:
`competitors`, `objection_categories`, `feature_gaps`, `value_metrics`,
`industries`, `discovery_signals`, `champion_indicators`, `learning`.

Stage IDs are discovered, not guessed. Run:
```bash
python scripts/discover_stages.py
```
and the onboarding skill walks you through confirming the output.

---

## Files and directories to know

| Path | What it does |
|---|---|
| `scripts/run_nightly.py` | Nightly orchestration |
| `scripts/meddicc_agent.py` | Generator + evaluator + reflection loop |
| `scripts/etl_deals.py` / `scripts/etl_calls.py` | Build deal index + call cache |
| `scripts/analytics/` | Weekly waterfall, forecast, win/loss, snapshots |
| `scripts/enrichment/` | Objections, feature gaps, signals, participants |
| `api/main.py` | FastAPI server for the Slack agent |
| `api/router.py` | Intent classification, routing, synthesis, self-assessment |
| `api/handlers.py` | 16 precomputed query handlers |
| `api/tools.py` | Typed query primitives for the dynamic path |
| `api/rubric.py` / `api/stage_requirements.py` | Coaching bands + stage-aware risk |
| `prompts/CLAUDE.md` | Generator instructions, edit to calibrate |
| `prompts/evaluator_rubric.md` | Evaluation criteria, auto-improves |
| `config/client.yaml` / `config/context.yaml` | Your pipeline + market context |
| `scripts/migrations/` | Supabase schema, 001–027 |
| `skills/` | Setup + client-context onboarding skills |
| `docs/` | Adapter guide, data schema |
| `deliverable/` | Standalone ready-to-deploy prompt package + examples |
| `memory/` | Call cache, learnings, run metadata (gitignored contents) |
| `output/` | MEDDICC analysis files |

---

## Costs

| Scenario | Cost |
|---|---|
| First full pipeline run | ~$3-5 |
| Nightly steady state | ~$0.10-0.30 |
| Slack agent per question | ~$0.01-0.05 |
| Monthly total (nightly + light Slack use) | ~$10-20 |

Haiku handles classification and evaluation; Sonnet handles generation
and synthesis. Every LLM call is tracked (`scripts/token_tracker.py`).

---

## Design rules (house style)

- Haiku for classification and evaluation; Sonnet for generation and
  synthesis.
- Cache first, API second.
- Individual deal failures must never stop a nightly run.
- Never delete a test to make the suite pass — fix the underlying code.
- The Slack agent self-assesses answer **tone** as well as correctness
  (lead with the headline, always give a bottom line). See
  `api/assessor.py`.

---

## What is and isn't in this repo

**In and runnable:** nightly MEDDICC agent, weekly analytics,
enrichment, the full CRO Slack agent (`api/`), all 27 migrations, both
onboarding skills. Every `api/*` import resolves and the package boots
with `uvicorn api.main:app`.

**You provide at deploy time:** your credentials, your Railway
instance, and your two Zaps. No prior client's data, domains, stage
IDs, or secrets ship in this template. The generator prompt
(`prompts/CLAUDE.md`) carries a few illustrative scoring examples with
placeholder names; the onboarding skill rewrites it for your team.
