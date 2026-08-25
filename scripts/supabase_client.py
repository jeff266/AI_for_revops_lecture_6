#!/usr/bin/env python3
"""
Supabase Writer Client for MEDDICC Agent

Handles parallel writes to Supabase alongside GitHub for:
- Deal metadata
- Call transcripts with signal detection (feature gaps, objections)
- MEDDICC analyses with full scoring breakdown
"""
from supabase import create_client, Client
import os
import re
import json
from datetime import datetime, date
from typing import Optional

FEATURE_GAP_KEYWORDS = [
    'feature gap', 'missing feature', "doesn't support", "can't do",
    'limitation', 'not able to', 'workaround', 'not supported',
    'lack of', 'unable to', 'no support for'
]

OBJECTION_KEYWORDS = [
    'concern', 'worried', 'not sure', 'pushback', 'hesitant',
    'risk', 'what about', 'but what', 'challenge', 'obstacle',
    "can't commit", 'too expensive', 'timeline', 'vendor risk'
]

def _has_keyword(text: str, keywords: list) -> bool:
    """Check if text contains any of the keywords."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)

def _safe_int(val) -> Optional[int]:
    """Safely convert value to int."""
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _safe_numeric(val) -> Optional[float]:
    """Safely convert value to float, handling formatted numbers."""
    try:
        v = str(val).replace('$', '').replace(',', '').strip()
        return float(v) if v else None
    except (ValueError, TypeError):
        return None

def _safe_date(val) -> Optional[str]:
    """Safely convert value to ISO date string."""
    if not val:
        return None
    try:
        if isinstance(val, (date, datetime)):
            return val.isoformat()[:10]
        s = str(val).strip()
        return s[:10] if len(s) >= 10 else None
    except Exception:
        return None


def _coerce_in_values(val):
    """An `in_` filter needs a COLLECTION. If a bare string reaches postgrest's
    .in_(), postgrest iterates it CHARACTER BY CHARACTER — a single deal_id
    "60785721693" becomes in.(6,0,7,8,5,...) and the query returns nonsense.

    Production fix #1: _coerce_in_values - deal ID string iteration bug.
    Live Bestseller incident: a comma-joined id string produced a filter on
    single digits and quote chars. Coerce here so no caller can trip it:
      - a str is split on commas if it contains any (a joined id list), else
        treated as ONE id → [val];
      - any other non-collection scalar becomes [val];
      - a list/tuple/set passes through as a list.
    Each element is stringified and de-quoted."""
    if isinstance(val, (list, tuple, set)):
        items = list(val)
    elif isinstance(val, str):
        items = val.split(",") if "," in val else [val]
    else:
        items = [val]
    out = []
    for v in items:
        s = str(v).strip().strip('"').strip("'").strip()
        if s:
            out.append(s)
    return out


def select_all(sb, table, columns='*', filters=None, page_size=1000):
    """Paginated select — PostgREST caps unpaginated responses
    at 1,000 rows silently."""
    rows, page = [], 0
    while True:
        q = sb.table(table).select(columns)
        for f in (filters or []):
            op = f[0]
            if op == "__not_null__":
                q = q.not_.is_(f[1], "null")
            elif op == "is_":
                q = q.is_(f[1], f[2])
            elif op == "ilike":
                q = q.ilike(f[1], f[2])
            elif op == "in_" or op == "in":
                # Fix A1: "in" is reserved keyword, always use "in_" method
                # Production fix #1: Coerce value to list before .in_() to prevent
                # character iteration (deal_id string → in.(6,0,1,4,...))
                q = q.in_(f[1], _coerce_in_values(f[2]))
            else:
                q = getattr(q, op)(f[1], f[2])
        batch = (q.range(page*page_size,
                 (page+1)*page_size - 1).execute().data
                 or [])
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        page += 1


class SupabaseWriter:
    """Client for writing MEDDICC agent data to Supabase."""

    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_KEY')
        if not url or not key:
            raise ValueError(
                'SUPABASE_URL and SUPABASE_SERVICE_KEY must be set')
        self.client: Client = create_client(url, key)

    def upsert_deal(self, deal: dict) -> None:
        """Upsert a deal from the deal index or analytics ETL."""
        deal_id = str(deal['deal_id'])

        # Base fields (active/history/analytics modes)
        row = {
            'deal_id':       deal_id,
            'company_name':  deal.get('company_name', ''),
            'company_slug':  deal.get('company_slug', ''),
            'stage':         deal.get('stage'),
            'pipeline':      deal.get('pipeline'),
            'arr_usd':       _safe_numeric(deal.get('arr')),
            'close_date':    _safe_date(deal.get('close_date')),
            'owner_email':   deal.get('owner'),
            'last_analyzed': deal.get('last_analyzed'),
            'updated_at':    datetime.now().isoformat(),
        }

        # Preserve existing values for fields that should never be cleared
        # If company_name or company_slug is None, exclude from upsert
        PRESERVE_IF_EXISTING = {'company_name', 'company_slug'}
        row = {k: v for k, v in row.items()
               if k not in PRESERVE_IF_EXISTING or v is not None}

        # Analytics-specific fields
        if 'deal_status' in deal:
            row['deal_status'] = deal['deal_status']
        if 'pipeline_id' in deal:
            row['pipeline_id'] = deal['pipeline_id']
        if 'stage_id' in deal:
            row['stage_id'] = deal['stage_id']
        if 'deal_value' in deal:
            row['deal_value'] = _safe_numeric(deal['deal_value'])
        if 'lost_reason' in deal:
            row['lost_reason'] = deal.get('lost_reason')
        if 'stage_source' in deal:
            row['stage_source'] = deal['stage_source']
        if 'create_date' in deal:
            row['create_date'] = _safe_date(deal['create_date'])
        if 'days_to_close' in deal:
            row['days_to_close'] = _safe_int(deal['days_to_close'])

        # Phase B.6 cardinal-rule fields
        if 'new_arr' in deal:
            row['new_arr'] = _safe_numeric(deal['new_arr'])
        if 'expansion_arr' in deal:
            row['expansion_arr'] = _safe_numeric(deal['expansion_arr'])
        if 'prior_arr' in deal:
            row['prior_arr'] = _safe_numeric(deal['prior_arr'])
        if 'sao' in deal:
            row['sao'] = deal.get('sao')  # Boolean, no conversion needed
        if 'forecast_category' in deal:
            row['forecast_category'] = deal.get('forecast_category')

        # Segmentation fields (migration 013)
        if 'company_id' in deal:
            row['company_id'] = deal.get('company_id')
        if 'company_domain' in deal:
            row['company_domain'] = deal.get('company_domain')  # Domain from HubSpot
        if 'company_employee_count' in deal:
            row['company_employee_count'] = _safe_int(deal['company_employee_count'])
        if 'segment' in deal:
            row['segment'] = deal.get('segment')
        if 'segment_reason' in deal:
            row['segment_reason'] = deal.get('segment_reason')  # Diagnostic field

        # Handle highest_stage_order_reached (max logic)
        if 'current_stage_order' in deal:
            current_order = deal['current_stage_order']
            # Read existing value
            existing = self.client.table('deals')\
                .select('highest_stage_order_reached')\
                .eq('deal_id', deal_id)\
                .execute()

            existing_highest = 0
            if existing.data and len(existing.data) > 0:
                existing_highest = existing.data[0].get('highest_stage_order_reached') or 0

            # Use max of current and existing
            row['highest_stage_order_reached'] = max(current_order, existing_highest)

        self.client.table('deals').upsert(
            row, on_conflict='deal_id').execute()

    def upsert_call(self, call: dict, company_name: str) -> None:
        """Upsert a call from the call cache."""
        summary = (call.get('formatted_summary')
                   or call.get('summary') or '')
        self.client.table('calls').upsert({
            'call_id':              str(call['id']),
            'company_slug':         call.get('company_slug', ''),
            'company_name':         company_name,
            'source':               call.get('source', ''),
            'call_date':            _safe_date(call.get('date')),
            'duration_minutes':     _safe_numeric(
                                        call.get('duration_minutes')),
            'title':                call.get('title', ''),
            'formatted_summary':    summary,
            'competitors_mentioned': call.get('competitors_mentioned'),
            'has_feature_gap':      _has_keyword(summary,
                                        FEATURE_GAP_KEYWORDS),
            'has_objection':        _has_keyword(summary,
                                        OBJECTION_KEYWORDS),
            'updated_at':           datetime.now().isoformat(),
        }, on_conflict='call_id').execute()

    def insert_analysis(self, deal_id: str, company_name: str,
                        result: dict, scores: dict,
                        output_file: str, component_details: dict = None) -> None:
        """Insert a new MEDDICC analysis row."""
        self.client.table('analyses').insert({
            'deal_id':                 str(deal_id),
            'company_name':            company_name,
            'overall_score':           _safe_int(
                                           scores.get('overall_score')),
            'status':                  scores.get('status', 'red'),
            'metrics_score':           _safe_int(
                                           scores.get('metrics_score')),
            'economic_buyer_score':    _safe_int(
                                           scores.get(
                                               'economic_buyer_score')),
            'decision_criteria_score': _safe_int(
                                           scores.get(
                                               'decision_criteria_score')),
            'decision_process_score':  _safe_int(
                                           scores.get(
                                               'decision_process_score')),
            'pain_score':              _safe_int(
                                           scores.get('pain_score')),
            'champion_score':          _safe_int(
                                           scores.get('champion_score')),
            'competition_score':       _safe_int(
                                           scores.get(
                                               'competition_score')),
            'iterations':              result.get('iterations', 1),
            'passed':                  result.get('passed', False),
            'full_analysis_text':      result.get('draft', ''),
            'summary':                 scores.get('summary', ''),
            'output_file':             output_file,
            'component_details':       json.dumps(component_details) if component_details else None,
        }).execute()

    def bulk_upsert_calls(self, calls: list,
                          company_name: str) -> int:
        """Upsert multiple calls at once. Returns count upserted."""
        if not calls:
            return 0
        rows = []
        for call in calls:
            call['company_slug'] = call.get('company_slug', '')
            summary = (call.get('formatted_summary')
                       or call.get('summary') or '')
            rows.append({
                'call_id':            str(call['id']),
                'company_slug':       call.get('company_slug', ''),
                'company_name':       company_name,
                'source':             call.get('source', ''),
                'call_date':          _safe_date(call.get('date')),
                'duration_minutes':   _safe_numeric(
                                          call.get('duration_minutes')),
                'title':              call.get('title', ''),
                'formatted_summary':  summary,
                'competitors_mentioned': call.get(
                    'competitors_mentioned'),
                'has_feature_gap':    _has_keyword(
                    summary, FEATURE_GAP_KEYWORDS),
                'has_objection':      _has_keyword(
                    summary, OBJECTION_KEYWORDS),
                'updated_at':         datetime.now().isoformat(),
            })
        self.client.table('calls').upsert(
            rows, on_conflict='call_id').execute()
        return len(rows)

    def bulk_upsert_transcripts(self, rows: list, chunk: int = 25) -> int:
        """
        Upsert call_transcripts rows (STORE_AND_BACKFILL_TRANSCRIPTS).

        Chunked because a transcript row is 40-60KB — one big upsert of the
        whole book would be a multi-MB request. Rows are pre-shaped by
        transcript_store.build_transcript_row (which enforces NULL-never-empty
        and the unavailable_reason invariant). Returns count upserted.

        Args:
            rows: List of transcript rows from build_transcript_row()
            chunk: Chunk size for batching (default 25)

        Returns:
            Count of rows upserted
        """
        rows = [r for r in (rows or []) if r and r.get("call_id")]
        if not rows:
            return 0
        for i in range(0, len(rows), chunk):
            self.client.table('call_transcripts').upsert(
                rows[i:i + chunk], on_conflict='call_id').execute()
        return len(rows)
