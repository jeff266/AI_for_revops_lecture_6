"""
Database helper functions for CRO Slack Agent.
All functions use Supabase client to read/write conversation state,
quota targets, and unanswered query logs.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

_sb = None

def get_supabase() -> Client:
    """Singleton Supabase client."""
    global _sb
    if _sb is None:
        _sb = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"]
        )
    return _sb


def unpack_jsonb(value, default=None):
    """
    Safely unpack a Supabase JSONB column that may be
    returned as a string, dict, list, or None.
    Prevents AttributeError crashes from iterating
    unparsed JSON strings.

    Usage:
        data = unpack_jsonb(row.get("component_details"), {})
        items = unpack_jsonb(row.get("key_factors"), [])
    """
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default if default is not None else {}
    return default if default is not None else {}


# Valid Anthropic message roles
VALID_ROLES = {"user", "assistant"}

# Entity context role - stored in history but never sent to Anthropic
ENTITY_ROLE = "entity_context"

# Result cache reference role - stored in history but never sent to Anthropic
CACHE_ROLE = "result_cache_ref"

# TTL for cached result payloads (matches G.6 entity staleness guard)
CACHE_TTL_MINUTES = 30

# Handlers that legitimately never carry entities (follow-ups meaningless)
# Keep this list SMALL - handlers that COULD support follow-ups should get
# cache_payload instead of a whitelist entry
AGGREGATE_HANDLERS = {"query_rubric"}


def extract_entity_context(tool_results: dict, sb=None) -> dict:
    """
    Schema-driven entity extraction using entity_registry.

    Queries entity_registry to discover all registered entity types,
    then scans tool_results for any registered ID columns. Extracts
    both entity IDs and their human-readable labels.

    Automatically supports new entity types (campaign, account, ticket)
    without code changes — just register them in entity_registry.

    Returns legacy shape {"deal_ids": [...], "company_names": [...]}
    for backward compatibility with existing handlers, routing, and
    stored thread history.

    Args:
        tool_results: Handler output dict containing entity data
        sb: Optional Supabase client (for testing); defaults to singleton
    """
    import logging
    logger = logging.getLogger(__name__)

    # Load entity registry (schema-driven)
    if sb is None:
        sb = get_supabase()
    try:
        registry_result = sb.table("entity_registry").select("*").execute()
    except Exception as e:
        logger.error(f"[ENTITY_EXTRACT] failed to load entity_registry: {e}")
        return {"deal_ids": [], "company_names": []}

    if not registry_result.data:
        logger.warning("[ENTITY_EXTRACT] entity_registry is empty - no entity types registered")
        return {"deal_ids": [], "company_names": []}

    # Build registry lookup: {id_column: {entity_type, entity_label_column, table}}
    registry = {}
    for entry in registry_result.data:
        id_col = entry["id_column"]
        registry[id_col] = {
            "entity_type": entry["entity_type"],
            "entity_label_column": entry["entity_label_column"],
            "table": entry["supabase_table"]
        }

    logger.info(f"[ENTITY_EXTRACT] registry loaded: {list(registry.keys())}")
    logger.info(f"[ENTITY_EXTRACT] tool_results keys: {list(tool_results.keys())}")

    # Extract entities: {entity_type: {"ids": [...], "labels": [...]}}
    entities = {}

    # 1. Scan list-valued keys for rows containing registered entity ID columns
    rows = tool_results.get("rows", [])

    if not rows:
        # Check other list-valued keys (handles structured handlers like waterfall)
        for key, value in tool_results.items():
            if isinstance(value, list) and value:
                first_item = value[0] if value else None
                if isinstance(first_item, dict):
                    # Check if this list contains any registered entity ID column
                    for id_col in registry.keys():
                        if id_col in first_item:
                            rows = value
                            logger.info(f"[ENTITY_EXTRACT] using '{key}' list with {len(rows)} items")
                            break
                if rows:
                    break

    if not rows:
        logger.info(f"[ENTITY_EXTRACT] no entity-bearing lists found")

    # 2. Extract entities from rows
    # IMPORTANT: Process ALL rows first, dedupe, THEN cap at 20
    # (not rows[:20] before dedup - that misses duplicates beyond row 20)
    if rows:
        for r in rows:
            if isinstance(r, dict):
                for id_col, meta in registry.items():
                    entity_id = r.get(id_col)
                    if entity_id:
                        entity_type = meta["entity_type"]
                        label_col = meta["entity_label_column"]
                        label = r.get(label_col, "")

                        if entity_type not in entities:
                            entities[entity_type] = {"ids": [], "labels": []}

                        entities[entity_type]["ids"].append(entity_id)
                        if label:
                            entities[entity_type]["labels"].append(label)

        # Deduplicate IDs and labels, preserving order
        for entity_type in entities:
            # Use dict.fromkeys() to preserve order while deduping
            entities[entity_type]["ids"] = list(dict.fromkeys(entities[entity_type]["ids"]))
            entities[entity_type]["labels"] = list(dict.fromkeys(entities[entity_type]["labels"]))

            # Cap at 20 AFTER dedup
            entities[entity_type]["ids"] = entities[entity_type]["ids"][:20]
            entities[entity_type]["labels"] = entities[entity_type]["labels"][:20]

    # 3. Nested single-entity special case (registry-driven)
    # Handles returns like {"deal": {"deal_id": "...", "company_name": "..."}}
    # from query_deal_deep_dive and similar single-entity handlers
    for id_col, meta in registry.items():
        entity_type = meta["entity_type"]
        nested = tool_results.get(entity_type, {})
        if isinstance(nested, dict):
            entity_id = nested.get(id_col)
            if entity_id:
                if entity_type not in entities:
                    entities[entity_type] = {"ids": [], "labels": []}

                # Avoid duplicates
                if entity_id not in entities[entity_type]["ids"]:
                    entities[entity_type]["ids"].append(entity_id)
                    logger.info(f"[ENTITY_EXTRACT] found nested {entity_type}: {id_col}={entity_id}")

                    label_col = meta["entity_label_column"]
                    label = nested.get(label_col, "")
                    if label and label not in entities[entity_type]["labels"]:
                        entities[entity_type]["labels"].append(label)

    logger.info(f"[ENTITY_EXTRACT] schema-driven extraction: {entities}")

    # 4. Extract owner emails (rep_email, sdr_email, owner_email) for thread context
    # These are NOT in entity_registry but handlers emit them after name resolution.
    # Save to thread context so follow-ups ("their pipeline", "their metrics") scope
    # to the same rep/SDR without re-specifying the name.
    owner_emails = {}
    for key in ("rep_email", "sdr_email", "owner_email"):
        value = tool_results.get(key)
        if value and isinstance(value, str):
            owner_emails[key] = value
            logger.info(f"[ENTITY_EXTRACT] found {key}: {value}")

    # Convert to legacy shape for backward compatibility
    return _to_legacy_entity_shape(entities, owner_emails)


def _to_legacy_entity_shape(entities: dict, owner_emails: dict = None) -> dict:
    """
    Convert schema-driven entity dict to legacy shape for backward compatibility.

    The legacy shape {"deal_ids": [...], "company_names": [...], "rep_email": "...", "sdr_email": "..."}
    is required by:
    - save_thread() storage (db.py:325)
    - get_prior_entities() retrieval (db.py:363)
    - router.py entity_params construction (672-674, 713-714)
    - All bulk query handlers (handlers.py:71, 171, 352, 734, 747, 756, 764)

    Args:
        entities: Schema-driven format from entity_registry scan:
            {
                "deal": {"ids": ["D1", "D2"], "labels": ["Acme", "Globex"]},
                "company": {"ids": ["C1"], "labels": ["Acme"]},
                "call": {"ids": ["call_123"], "labels": ["Discovery call"]},
                ...
            }
        owner_emails: Owner email entities extracted from tool_results top-level:
            {
                "rep_email": "christian@example.com",
                "sdr_email": "jake@example.com",
                "owner_email": "christian@example.com"
            }

    Returns:
        Legacy format:
            {
                "deal_ids": ["D1", "D2"],
                "company_names": ["Acme", "Globex"],
                "rep_email": "christian@example.com",  # if present
                "sdr_email": "jake@example.com"        # if present
            }

    Mapping:
    - deal_ids: IDs from "deal" entity type
    - company_names: Labels from "deal" entity type (company_name field)
    - rep_email, sdr_email: Directly from owner_emails (for thread-context follow-ups)

    Note: Other entity types (company, call, campaign, etc.) are extracted
    but not included in legacy output. They'll be added to the shape in
    Phase G.8 Task 5 when handlers consume them.
    """
    import logging
    logger = logging.getLogger(__name__)

    deal_data = entities.get("deal", {"ids": [], "labels": []})

    legacy = {
        "deal_ids": deal_data["ids"],
        "company_names": deal_data["labels"]
    }

    # Add owner emails to legacy shape for thread-context follow-ups
    if owner_emails:
        for key in ("rep_email", "sdr_email", "owner_email"):
            if key in owner_emails:
                legacy[key] = owner_emails[key]

    # Log if non-deal entities were extracted (informational)
    other_types = [et for et in entities.keys() if et != "deal"]
    if other_types:
        logger.info(f"[ENTITY_EXTRACT] extracted {other_types} entities "
                   f"(not included in legacy shape)")

    logger.info(f"[ENTITY_EXTRACT] legacy shape: "
                f"{len(legacy['deal_ids'])} deal_ids, "
                f"{len(legacy['company_names'])} company_names, "
                f"owner_emails={list(owner_emails.keys()) if owner_emails else []}")

    return legacy


# ══════════════════════════════════════════════════════════════
# RESULT CACHE LAYER (G.7)
# ══════════════════════════════════════════════════════════════

def make_result_key(thread_ts: str, handler_name: str, question: str) -> str:
    """
    Deterministic key so the same question in the same thread
    overwrites rather than accumulating rows.

    Uses SHA256 hash to keep keys compact while avoiding collisions.
    """
    import hashlib
    raw = f"{thread_ts}:{handler_name}:{question}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"rc_{digest}"


def save_result_cache(sb: Client, thread_ts: str, handler_name: str,
                      question: str, payload: dict) -> str | None:
    """
    Store a full result payload for later retrieval.
    Returns the result_key, or None if nothing worth caching.

    Only caches when payload actually contains row data —
    don't fill the table with empty aggregates.

    IMPORTANT: Uses timedelta for expiry, NOT modular arithmetic.
    Prior bug: now.replace(hour=(now.hour+24)%24) is no-op at hour 23.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Count rows across all list-valued keys
    row_count = 0
    for v in payload.values():
        if isinstance(v, list):
            row_count += len(v)

    if row_count == 0:
        return None

    key = make_result_key(thread_ts, handler_name, question)
    # CORRECT expiry computation using timedelta
    expires = datetime.now(timezone.utc) + timedelta(minutes=CACHE_TTL_MINUTES)

    sb.table("result_cache").upsert({
        "result_key":   key,
        "thread_ts":    thread_ts,
        "handler_name": handler_name,
        "question":     question[:500],  # Truncate long questions
        "payload":      json.dumps(payload),  # JSONB storage
        "row_count":    row_count,
        "expires_at":   expires.isoformat(),
    }, on_conflict="result_key").execute()

    logger.info(f"[CACHE] stored {row_count} rows under {key} "
                f"(handler={handler_name}, ttl={CACHE_TTL_MINUTES}m)")
    return key


def load_result_cache(sb: Client, thread_ts: str) -> dict | None:
    """
    Retrieve the most recent non-expired cached payload for a thread.
    Returns the payload dict, or None.

    Uses unpack_jsonb() because JSONB columns can come back as str or dict.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        now_iso = datetime.now(timezone.utc).isoformat()

        # Query for non-expired cache entries in this thread
        result = sb.table("result_cache")\
            .select("result_key,handler_name,question,payload,row_count,created_at,expires_at")\
            .eq("thread_ts", thread_ts)\
            .gt("expires_at", now_iso)\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        if not result.data:
            logger.info(f"[CACHE] no live cache for thread {thread_ts}")
            return None

        hit = result.data[0]
        logger.info(f"[CACHE] hit {hit['result_key']} — "
                   f"{hit['row_count']} rows from handler={hit['handler_name']}")

        # unpack_jsonb handles both string and dict JSONB returns
        return unpack_jsonb(hit.get("payload"))

    except Exception as e:
        logger.error(f"[CACHE] load failed: {e}")
        return None


def load_thread(sb: Client, thread_ts: str) -> list:
    """Load last 3 Q&A pairs. Filters out entity_context
    role — those are for local use only, not Anthropic."""
    try:
        r = sb.table("conversation_threads")\
              .select("history")\
              .eq("thread_ts", thread_ts)\
              .execute()
        if r.data:
            hist = unpack_jsonb(r.data[0].get("history"), [])
            # Keep entity_context in the full history
            # (used by get_prior_entities below)
            return hist[-9:]  # 3 Q&A pairs + entity entries
    except Exception:
        pass
    return []

def save_thread(sb: Client, thread_ts: str, channel: str,
                history: list, question: str, answer: str,
                tool_results: dict, handler_name: str = "unknown"):
    """Append Q&A + optional entity context to thread.

    Args:
        tool_results: REQUIRED - must pass {} explicitly for paths with no data.
                     Making this required (no default) turns silent omissions
                     into immediate TypeErrors.
        handler_name: Handler that produced this answer, for negative-case logging.
    """
    import logging
    logger = logging.getLogger(__name__)

    history = history[-6:]  # rolling window

    # ═══════════════════════════════════════════════════════════════
    # CRITICAL: Strip cache_payload BEFORE any synthesis-facing use
    # ═══════════════════════════════════════════════════════════════
    # Failure mode is SILENT AND EXPENSIVE: if cache_payload leaks into
    # synthesis, full deal rows go into the prompt (3-5K wasted tokens).
    # Nothing in current logging would catch it. Assert + size log required.

    cache_payload = tool_results.pop("cache_payload", None)

    # LOAD-BEARING ASSERTION: verify strip succeeded
    assert "cache_payload" not in tool_results, \
        "cache_payload leaked into synthesis path"

    # Size log: makes leaks VISIBLE in Railway without needing a test
    synth_size = len(json.dumps(tool_results, default=str))
    logger.info(f"[SYNTH] tool_results ~{synth_size} chars (handler={handler_name})")
    if synth_size > 20000:
        logger.warning(f"[SYNTH] oversized synthesis payload {synth_size} chars "
                      f"for handler={handler_name} — check for cache_payload leak "
                      f"or unbounded rows")

    # Extract entities from BOTH synthesis dict AND cache_payload
    # (aggregate handlers now yield deal_ids via cache_payload)
    entities = {}
    if tool_results:
        logger.info(f"[SAVE_THREAD] extracting entities from tool_results")
        entities = extract_entity_context(tool_results, sb)

    if cache_payload:
        logger.info(f"[SAVE_THREAD] extracting entities from cache_payload")
        cache_entities = extract_entity_context(cache_payload, sb)
        # Merge cache entities into main entity dict
        for deal_id in cache_entities.get("deal_ids", []):
            if deal_id not in entities.get("deal_ids", []):
                entities.setdefault("deal_ids", []).append(deal_id)
        for company_name in cache_entities.get("company_names", []):
            if company_name not in entities.get("company_names", []):
                entities.setdefault("company_names", []).append(company_name)

    if not tool_results and not cache_payload:
        logger.info(f"[SAVE_THREAD] empty tool_results (handler={handler_name})")

    # Check extraction success BEFORE modifying history
    has_entities = bool(entities.get("deal_ids") or entities.get("company_names"))
    has_tool_data = bool(tool_results) and any(
        isinstance(v, list) and v for v in tool_results.values())

    # LOUD negative-case warning: tool_results had data but extraction got ZERO entities
    # Exclude handlers that legitimately never carry entities
    if (handler_name not in AGGREGATE_HANDLERS
        and has_tool_data and not has_entities):
        logger.warning(f"[ENTITY] save_thread stored ZERO entities "
                      f"for handler={handler_name} despite non-empty tool_results "
                      f"— keys: {list(tool_results.keys())}")

    history += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]

    # Store entity context as separate entry if entities found
    if has_entities:
        # Add timestamp for staleness checking
        entities["resolved_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"[SAVE_THREAD] saving entity_context: "
                   f"{len(entities.get('deal_ids', []))} deal_ids, "
                   f"{len(entities.get('company_names', []))} company_names")
        history.append({
            "role": ENTITY_ROLE,
            "content": json.dumps(entities),
            "turn": len(history),
        })
    else:
        logger.info(f"[SAVE_THREAD] no entities to save (handler={handler_name})")

    # Store result cache payload if one exists
    if cache_payload:
        result_key = save_result_cache(sb, thread_ts, handler_name, question, cache_payload)
        if result_key:
            # Append cache reference to history (filtered from API calls like ENTITY_ROLE)
            history.append({
                "role": CACHE_ROLE,
                "content": result_key,
                "turn": len(history),
            })

    now = datetime.now(timezone.utc)
    sb.table("conversation_threads").upsert({
        "thread_ts":   thread_ts,
        "channel_id":  channel,
        "history":     json.dumps(history),
        "last_active": now.isoformat(),
        "expires_at":  (now + timedelta(hours=24)).isoformat(),
    }, on_conflict="thread_ts").execute()

def get_api_history(history: list) -> list:
    """
    Filter history for Anthropic API calls.
    Removes entity_context entries — these are internal only.
    """
    return [m for m in history
            if m.get("role") in ("user", "assistant")]


def get_prior_entities(history: list) -> dict:
    """
    Extract the most recent entity_context from history.
    Returns {"deal_ids": [...], "company_names": [...], "rep_email": "...", "sdr_email": "..."}
    or empty dict if no prior entities found.

    Thread-context entities enable follow-ups like:
    - "show me Christian's pipeline" → saves rep_email
    - "which of those are closing this quarter?" → uses saved rep_email
    """
    for msg in reversed(history):
        if msg.get("role") == ENTITY_ROLE:
            content = msg.get("content", "{}")
            try:
                return (json.loads(content)
                        if isinstance(content, str)
                        else content)
            except Exception:
                pass
    return {}


def log_unanswered(sb: Client, question: str, user_id: str,
                    channel: str, thread_ts: str,
                    reason: str):
    """
    Log a question the agent couldn't answer.
    Reasons: 'no_data' | 'out_of_scope' | 'ambiguous'
    """
    sb.table("unanswered_queries").insert({
        "question":   question,
        "asked_by":   user_id,
        "channel_id": channel,
        "thread_ts":  thread_ts,
        "reason":     reason,
    }).execute()

def is_admin(user_id: str) -> bool:
    """
    Check if user_id is in config admin list.
    Returns False if config not found or user not in list.
    """
    try:
        import yaml
        from pathlib import Path
        cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
        cfg = yaml.safe_load(open(cfg_path))
        admins = (cfg.get("admin", {})
                     .get("slack_user_ids", []))
        return user_id in admins
    except Exception:
        return False
