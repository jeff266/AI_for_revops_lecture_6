# Adapter Guide — CRM, Storage, and Call Adapters

The template uses three adapter layers to isolate vendor-specific code:

1. **CRM Adapter** (`adapters/crm/`) — HubSpot, Salesforce, Pipedrive
2. **Storage Adapter** (`adapters/storage/`) — Supabase, Snowflake, BigQuery
3. **Call Adapter** (`adapters/calls/`) — Fireflies, Gong, Apollo, Fathom, Avoma

Each wraps a vendor SDK behind a small interface. Production code (ETL, nightly agent, progressive scorer) only ever talks to the interface, never imports vendor SDKs directly. This pattern prevents drift — porting a feature that calls a vendor SDK directly would introduce a second pattern into a repo with a working one.

**Phase 4 Note:** Progressive scoring (call_scorer.py, rollup_deal_scores.py) writes to BOTH layers — CRM writes (individual HubSpot properties for UI/filters/workflows) + Storage writes (JSONB in Supabase for methodology-agnostic history). The split is intentional and required. See "Two-Layer Storage Pattern" below.

---

## Two-Layer Storage Pattern

Deal-level scores and call-level scores are written to TWO places with different purposes:

### Layer 1: CRM (HubSpot)
**Purpose:** Individual properties for CRM UI, filters, workflows, and reporting dashboards.

**What gets written:**
- `meddicc_champion_score`, `meddicc_economic_buyer_score`, etc.
- Real HubSpot custom fields (one per component)
- Component set varies by methodology (MEDDICC: 7, MEDDPIC: 8 with `paper_process`)
- Written via `HubSpotDealsClient.write_analysis()` (lines 416-453)
- Checks `if 'Champion' in components` before writing each score

**Why:** Sales teams work in HubSpot. They need scores as properties to build filters, trigger workflows, and see values in the deal sidebar.

### Layer 2: Storage (Supabase)
**Purpose:** JSONB aggregates for methodology-agnostic queries and historical analysis.

**What gets written:**
- `analyses.component_scores` JSONB: `{component_key: score}`
- `call_scores.component_scores` JSONB: `{component_key: score}` (Phase 4)
- `call_scores.evidence` JSONB: `{component_key: evidence_text}` (Phase 4)
- Written via `SupabaseWriter.insert_analysis()` and new `write_call_scores()` (Phase 4)
- Lives in `adapters/storage/supabase.py`, NOT the CRM adapter

**Why:** Enables queries like "show me all MEDDPIC deals" without schema changes. A MEDDPIC client gets `{"paper_process": 7, ...}` in JSONB; switching back to MEDDICC omits it. Zero migration required. Analytics queries (`slip_diagnosis.py`, `stage_score_hygiene.py`) read from here.

**CRITICAL:** Both layers are required. CRM-only loses query flexibility; storage-only breaks HubSpot workflows. Progressive scorer writes to BOTH.

---

## CRM Adapter (HubSpot)

**Location:** `adapters/crm/hubspot.py`

**Used by:** 8 production files including `discover_stages.py`, `run_nightly.py`, `hubspot_deals.py`

**Why:** All HubSpot operations route through `HubSpotDealsClient` to maintain a single pattern. Porting code that calls HubSpot directly introduces drift — exactly what Phases 1-3 exist to prevent.

### Core Interface

```python
from adapters.crm.hubspot import HubSpotDealsClient

client = HubSpotDealsClient()

# Write analysis results to deal properties
client.write_analysis(
    deal_id='12345',
    scores={'champion_score': 7, 'metrics_score': 8, ...},
    status='analyzed',
    summary='Deal shows strong champion alignment...',
    last_analyzed='2026-08-24T10:00:00Z'
)
```

**Methodology-aware writing (lines 444-447):** The adapter checks `if 'Champion' in components` before writing `meddicc_champion_score`. A SPICED client gets `spiced_pain_score` instead. Component keys come from `get_components()` in utils.py.

**Property naming convention:**
- Score: `{methodology}_{component_key}_score` (e.g., `meddicc_champion_score`)
- Status: `{methodology}_status`
- Summary: `{methodology}_analysis_summary`
- Last analyzed: `{methodology}_last_analyzed`

Override defaults in `config/client.yaml` under `hubspot.properties` if needed.

### Adding a New CRM

Create `adapters/crm/salesforce.py` and implement:

```python
class SalesforceClient:
    def write_analysis(self, deal_id, scores, status, summary, last_analyzed):
        """Write component scores as individual custom fields."""
        # Map component_key to Salesforce field API names
        # CRITICAL: Check get_components() to know which components to write

    def read_deal(self, deal_id, properties):
        """Fetch deal fields needed for analysis."""

    def search_deals(self, filters):
        """Find deals matching criteria."""
```

Then add to factory in `adapters/crm/__init__.py` and set `organization.crm: "Salesforce"` in `config/client.yaml`.

---

## Storage Adapter (Supabase)

**Location:** `adapters/storage/supabase.py`

**Used by:** Nightly agent, progressive scorer (Phase 4), analytics scripts

**Why:** Stores methodology-agnostic analysis history in JSONB. Enables queries without schema changes when switching methodologies.

### Core Interface

```python
from adapters.storage.supabase import SupabaseWriter

writer = SupabaseWriter()

# Write deal-level analysis
writer.insert_analysis(
    deal_id='12345',
    component_scores={'champion': 7, 'metrics': 8, ...},  # JSONB
    status='approved',
    summary='...',
    analyzed_at='2026-08-24T10:00:00Z'
)

# Write call-level scores (Phase 4)
writer.write_call_scores(
    call_id='abc-123',
    deal_id='12345',
    component_scores={'champion': 6, 'metrics': 7, ...},  # JSONB
    evidence={'champion': 'Quote: "Sarah is driving this..."', ...},  # JSONB
    text_source='transcript',
    model='claude-sonnet-4-5',
    scorer_version='progressive_v1'
)
```

**JSONB pattern (CRITICAL):** `component_scores` and `evidence` are JSONB columns, not fixed columns like `metrics_score`, `champion_score`. This enables methodology switching without migrations. A MEDDPIC client gets `{"paper_process": 7, ...}` with zero schema changes.

**Schema:** See `docs/data-schema.md` for full table definitions including indexes.

### Adding a New Storage Backend

Create `adapters/storage/snowflake.py` and implement:

```python
class SnowflakeWriter:
    def insert_analysis(self, deal_id, component_scores, status, summary, analyzed_at):
        """Write to ANALYSES table. component_scores must be JSON/VARIANT."""

    def write_call_scores(self, call_id, deal_id, component_scores, evidence, ...):
        """Write to CALL_SCORES table (Phase 4)."""

    def read_latest_analysis(self, deal_id):
        """Fetch most recent analysis for deal."""
```

Use native JSON types (Snowflake: VARIANT, BigQuery: JSON, Postgres: JSONB) for `component_scores` and `evidence`.

---

## Call Adapter (Call Intelligence Tools)

**Location:** `adapters/calls/`

**Used by:** ETL (`etl_calls.py`), nightly agent, progressive scorer

**Why:** Every call intelligence tool (Fireflies, Gong, Apollo, Fathom, Avoma) has different APIs. The adapter pattern isolates those differences.

### Adding a New Call Tool

**1. Implement `CallAdapter`**

Create `adapters/calls/<tool_slug>.py` and subclass the contract in `adapters/calls/base.py`:

```python
from .base import CallAdapter

class MyToolClient(CallAdapter):
    def search_by_company(self, company_name, since_date=None) -> list:
        """Return a list of call dicts for the company."""

    def format_summary(self, call) -> str:
        """Return an analysis-ready summary. Must be >100 chars for
        real calls (Guard 3 in the nightly agent)."""

    def get_meeting_attendees(self, call_id) -> list:
        """Return [{'name': ..., 'email': ...}, ...] or [] if the
        tool cannot provide attendees."""

    # test_connection() is optional; the default returns True.
```

Guidance:
- Read credentials from environment variables in `__init__` (never
  hardcode keys).
- `format_summary` is the field the cache stores as `formatted_summary`
  — keep it rich enough to clear the 100-char guard.
- If the tool exposes no attendee emails, return `[]` — that is valid.

**2. Register it in the factory**

Add a branch to `get_call_adapter` in `adapters/__init__.py`:

```python
if tool == 'mytool':
    from .calls.mytool import MyToolClient
    return MyToolClient()
```

Then set `call_tools.primary: mytool` in `config/client.yaml`. Nothing else imports the tool module directly — the factory is the only entry point.

**3. Add credentials to the setup skill**

Add the tool's API key(s) to the credentials interview in `skills/revops-agent-setup/SKILL.md` so fresh forks collect them, and remind the user to add them as GitHub Secrets.

Once these three steps are done, the ETL and nightly agent pick up the new tool automatically — no other code changes required.

---

## When to Use Adapters

**Always route through adapters for:**
- HubSpot operations → `HubSpotDealsClient` (NOT direct `hubspot` SDK imports)
- Supabase writes → `SupabaseWriter` (NOT direct `supabase.table().insert()`)
- Call fetching → `get_call_adapter()` factory (NOT direct Fireflies/Gong imports)

**Why:** Maintains single pattern throughout codebase. Porting code that bypasses adapters introduces drift — a second way to do the same thing.

**Example of correct usage (progressive scorer, Phase 4):**
```python
from adapters.crm.hubspot import HubSpotDealsClient
from adapters.storage.supabase import SupabaseWriter

crm = HubSpotDealsClient()
storage = SupabaseWriter()

# Write to BOTH layers
crm.write_analysis(deal_id, scores, ...)      # Individual HubSpot properties
storage.write_call_scores(call_id, scores, ...)  # JSONB in Supabase
```

**Example of incorrect usage:**
```python
import hubspot
client = hubspot.Client.create(access_token=token)
client.crm.deals.basic_api.update(deal_id, ...)  # ❌ Bypasses adapter
```

**Phase 4 Rule:** All HubSpot operations in ported files MUST route through `HubSpotDealsClient`. Porting HubSpot-direct calls introduces the exact drift Phases 1-3 exist to prevent.
