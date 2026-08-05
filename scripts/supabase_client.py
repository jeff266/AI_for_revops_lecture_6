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
        """Upsert a deal from the deal index."""
        self.client.table('deals').upsert({
            'deal_id':       str(deal['deal_id']),
            'company_name':  deal.get('company_name', ''),
            'company_slug':  deal.get('company_slug', ''),
            'stage':         deal.get('stage'),
            'pipeline':      deal.get('pipeline'),
            'arr_usd':       _safe_numeric(deal.get('arr')),
            'close_date':    _safe_date(deal.get('close_date')),
            'owner_email':   deal.get('owner'),
            'last_analyzed': deal.get('last_analyzed'),
            'updated_at':    datetime.now().isoformat(),
        }, on_conflict='deal_id').execute()

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
                        output_file: str) -> None:
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
