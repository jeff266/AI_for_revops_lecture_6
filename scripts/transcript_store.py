"""
Shared transcript fetch + assemble + metrics + row-shaping.

Handles multi-source fetch (Fireflies, Gong, Apollo) with:
- GraphQL body-level error parsing (rate limits in response body, not HTTP 429)
- Exponential backoff (15s/30s/60s for rate limits, 2s/4s/8s for other errors)
- Source-priority dedup (Fireflies > Gong > Apollo)
- Utterance normalization (seconds vs milliseconds)
- Metrics computation (talk time, questions, longest monologue)
- Terminal vs retryable failures (backfill_transcripts resume logic)

Ported from the reference implementation's scripts/transcript_store.py to close the 260-line
etl_calls.py gap (template 675 lines → the reference implementation 935 lines).
"""
import os
import time
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta, date


# Quality levels for call_transcripts.transcript_quality
FULL = "full"
PARTIAL = "partial"
FRAGMENTS_ONLY = "fragments_only"
UNAVAILABLE = "unavailable"

# An empty result (fetch succeeded, no sentences) on a call older than this is
# TERMINAL — a transcript will never appear (silent/failed recording), so resume
# must stop re-attempting it (else every future pass burns an API call on it).
# On a RECENT call the same emptiness is PENDING — the transcript may still be
# generating — so resume keeps retrying it. Recorders finalise within minutes to
# hours; 3 days is a safe cutoff. unavailable_reason carries the distinction as a
# "terminal:" / "retry:" prefix, read by is_done() — no extra column needed.
STILL_PROCESSING_DAYS = int(os.getenv("TRANSCRIPT_STILL_PROCESSING_DAYS", "3"))
TERMINAL = "terminal:"
RETRY = "retry:"


class RateLimited(Exception):
    """Raised when API returns rate-limit error (body or HTTP status)."""
    pass


def fetch_utterances(
    source: str,
    call_id: str,
    clients: Dict[str, Any],
    retries: int = 6,
    backoff: float = 2.0,
    throttle: float = 0.0
) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """
    Fetch normalized utterances from call source.

    Returns (utterances, error):
    - utterances: List of {speaker, text, start_seconds, end_seconds} dicts
    - error: Error message if fetch failed (None on success)

    Handles:
    - Rate-limit backoff (15s, 30s, 60s) vs other errors (2s, 4s, 8s)
    - GraphQL body-level error parsing (Fireflies returns 200 OK with errors in body)
    - Utterance normalization (Fireflies seconds, Apollo milliseconds)
    """
    if throttle > 0:
        time.sleep(throttle)

    attempt = 0
    last_error = None

    while attempt < retries:
        try:
            if source == 'fireflies':
                return _fetch_fireflies(call_id, clients), None
            elif source == 'apollo':
                return _fetch_apollo(call_id, clients), None
            elif source == 'gong':
                return _fetch_gong(call_id, clients), None
            else:
                return None, f"Unknown source: {source}"

        except RateLimited as e:
            # Rate limit: long backoff (15s, 30s, 60s)
            last_error = str(e)
            wait = 15 * (2 ** attempt)  # 15, 30, 60, 120...
            print(f"  Rate limited ({source}): {e} — waiting {wait}s")
            time.sleep(wait)
            attempt += 1

        except Exception as e:
            # Other error: short backoff (2s, 4s, 8s)
            last_error = str(e)
            wait = backoff * (2 ** attempt)  # 2, 4, 8, 16...
            print(f"  Error ({source}): {e} — retry {attempt+1}/{retries} in {wait}s")
            time.sleep(wait)
            attempt += 1

    # All retries exhausted
    return None, f"Failed after {retries} attempts: {last_error}"


def _fetch_fireflies(call_id: str, clients: Dict[str, Any]) -> List[Dict]:
    """
    Fetch Fireflies transcript at utterance level.

    GraphQL query for transcript.sentences (NOT summary).
    Fireflies returns rate limits in response body (not HTTP 429).
    """
    client = clients.get('fireflies')
    if not client:
        raise ValueError("Fireflies client not configured")

    # Use actual Fireflies GraphQL schema
    # Note: Fireflies uses 'transcriptId' not 'id' for the parameter name
    query = """
    query GetTranscript($transcriptId: String!) {
      transcript(id: $transcriptId) {
        id
        sentences {
          speaker_name
          text
          start_time
          end_time
        }
      }
    }
    """

    response = client._query(query, {"transcriptId": call_id})

    # Check for GraphQL body-level errors (the the reference implementation 88% failure bug)
    if response.get("errors"):
        msg = "; ".join(e.get("message", "")[:80] for e in response["errors"])
        if _is_rate_limit(msg):
            raise RateLimited(f"fireflies: {msg[:100]}")
        raise Exception(f"GraphQL error: {msg}")

    # Extract sentences
    data = response.get("data", {})
    transcript = data.get("transcript")
    if not transcript:
        return []

    sentences = transcript.get("sentences", [])

    # Normalize to common format (Fireflies already in seconds)
    utterances = []
    for s in sentences:
        speaker = s.get('speaker_name', 'Unknown')
        utterances.append({
            'speaker': speaker,
            'display_name': speaker,  # Fireflies has name only
            'text': s.get('text', ''),
            'start_seconds': s.get('start_time', 0),  # Already seconds
            'end_seconds': s.get('end_time', 0)
        })

    return utterances


def _fetch_apollo(call_id: str, clients: Dict[str, Any]) -> List[Dict]:
    """
    Fetch Apollo transcript at utterance level.

    Apollo format: fragments with start_time/end_time in milliseconds,
    participant_id, and per-word triples. the reference implementation field probe confirmed
    real durations enable correct talk-time computation.
    """
    client = clients.get('apollo')
    if not client:
        raise ValueError("Apollo client not configured")

    # Get full conversation with transcript
    response = client.get_conversation(call_id)

    if not response or 'transcript' not in response:
        return []

    transcript_list = response.get('transcript', [])

    # Normalize to common format (Apollo uses milliseconds)
    utterances = []
    for entry in transcript_list:
        # Apollo uses participant_id as speaker key
        speaker_id = entry.get('participant_id', 'Unknown')
        display_name = entry.get('display_name') or entry.get('speaker', speaker_id)

        utterances.append({
            'speaker': speaker_id,
            'display_name': display_name,
            'text': entry.get('words', ''),
            'start_seconds': (entry.get('start_time', 0) or 0) / 1000.0,  # ms → seconds
            'end_seconds': (entry.get('end_time', 0) or 0) / 1000.0
        })

    return utterances


def _fetch_gong(call_id: str, clients: Dict[str, Any]) -> List[Dict]:
    """
    Fetch Gong transcript at utterance level.

    CRITICAL LIMITATION: Gong's /calls/{id}/transcript API endpoint does NOT
    return timestamps (start/end times). Only speaker names and sentence text
    are available. This means:
    - Transcript text assembly works (utterances can be joined)
    - Talk-time metrics CANNOT be computed (no duration data)
    - Longest-monologue detection CANNOT run (no timing boundaries)
    - Question count works (text-based heuristic)

    The normalized output marks start_seconds and end_seconds as None to
    propagate the limitation — consumers must handle missing timing data.

    If Gong later adds timing to their API, update GongAdapter.get_transcript_utterances()
    and this normalizer to populate start_seconds/end_seconds.
    """
    client = clients.get('gong')
    if not client:
        raise ValueError("Gong client not configured")

    # Call Gong adapter's utterance method (returns list of {speaker, text})
    raw_utterances = client.get_transcript_utterances(call_id)

    if not raw_utterances:
        return []

    # Normalize to common format (Gong has NO timestamps)
    utterances = []
    for u in raw_utterances:
        speaker = u.get('speaker', 'Unknown')
        utterances.append({
            'speaker': speaker,
            'display_name': speaker,  # Gong has name only
            'text': u.get('text', ''),
            # Gong API limitation: no timing data available
            'start_seconds': None,
            'end_seconds': None
        })

    return utterances


def _is_rate_limit(error_message: str) -> bool:
    """
    Detect rate-limit errors from GraphQL body messages.

    Fireflies returns rate limits in response body (not HTTP 429).
    Common patterns: "rate limit", "too many requests", "quota exceeded"
    """
    msg_lower = error_message.lower()
    patterns = ['rate limit', 'too many requests', 'quota exceeded', 'throttl']
    return any(p in msg_lower for p in patterns)


def build_transcript_row(
    source: str,
    call_id: str,
    utterances: Optional[List[Dict]],
    error: Optional[str] = None,
    call_date: Optional[datetime] = None
) -> Dict:
    """
    Shape one call_transcripts row: assembled text + metrics, or 'unavailable'.

    Returns dict ready for sb.bulk_upsert_transcripts():
    {
        'call_id': str,
        'source': str,
        'transcript_text': str,
        'transcript_quality': 'full' | 'partial' | 'fragments_only' | 'unavailable',
        'total_utterances': int,
        'speaker_count': int,
        'total_duration_seconds': float,
        'metrics': {talk_time_seconds: {...}, question_count: {...}, ...},
        'fetched_at': datetime,
        'fetch_error': Optional[str]
    }

    Quality levels:
    - full: 100+ utterances, multiple speakers
    - partial: 10-99 utterances
    - fragments_only: 1-9 utterances
    - unavailable: 0 utterances or fetch error
    """
    row = {
        'call_id': call_id,
        'source': source,
        'fetched_at': datetime.utcnow()
    }

    # Handle fetch errors - always retryable
    if error:
        reason = f"{RETRY} {error}"
        row.update({
            'transcript_text': None,
            'transcript_quality': UNAVAILABLE,
            'unavailable_reason': reason,
            'total_utterances': 0,
            'speaker_count': 0,
            'total_duration_seconds': 0.0,
            'metrics': {},
            'fetch_error': error  # keep for backward compat
        })
        return row

    # Handle empty transcript (classify as TERMINAL or RETRY by call age)
    if not utterances:
        reason = _classify_empty_transcript(call_date)
        row.update({
            'transcript_text': None,
            'transcript_quality': UNAVAILABLE,
            'unavailable_reason': reason,
            'total_utterances': 0,
            'speaker_count': 0,
            'total_duration_seconds': 0.0,
            'metrics': {},
            'fetch_error': None  # keep for backward compat
        })
        return row

    # Assemble full transcript text
    transcript_text = "\n".join([
        f"{u['speaker']}: {u['text']}" for u in utterances
    ])

    # Compute metrics
    metrics = compute_metrics(utterances)

    # Determine quality level
    utterance_count = len(utterances)
    speaker_count = len(set(u['speaker'] for u in utterances))

    if utterance_count >= 100 and speaker_count > 1:
        quality = 'full'
    elif utterance_count >= 10:
        quality = 'partial'
    elif utterance_count >= 1:
        quality = 'fragments_only'
    else:
        quality = 'unavailable'

    # Total duration (last utterance end time, or 0.0 if no timing available)
    end_times = [u.get('end_seconds') for u in utterances if u.get('end_seconds') is not None]
    duration = max(end_times) if end_times else 0.0

    row.update({
        'transcript_text': transcript_text,
        'transcript_quality': quality,
        'unavailable_reason': None,  # NULL when transcript exists
        'total_utterances': utterance_count,
        'speaker_count': speaker_count,
        'total_duration_seconds': duration,
        'metrics': metrics,
        'fetch_error': None  # keep for backward compat
    })

    return row


def _classify_empty_transcript(call_date: Optional[datetime], as_of: Optional[date] = None) -> str:
    """
    Classify an empty result as TERMINAL (old call — no transcript will ever
    appear) or RETRY (recent call — may still be processing), by call age.

    Returns unavailable_reason string with TERMINAL or RETRY prefix.

    Args:
        call_date: The date/datetime of the call to classify
        as_of: Reference date for age calculation (default: today's date)
               Pinning this makes the function testable without patching the clock

    Threshold: STILL_PROCESSING_DAYS (default 3 days). Fireflies typically
    processes within hours, but 3 days is a safe cutoff before marking terminal.
    """
    if as_of is None:
        as_of = date.today()

    try:
        if isinstance(call_date, str):
            call_date_obj = datetime.fromisoformat(call_date[:10])
        elif isinstance(call_date, datetime):
            call_date_obj = call_date
        elif isinstance(call_date, date):
            call_date_obj = datetime.combine(call_date, datetime.min.time())
        else:
            call_date_obj = None

        if call_date_obj:
            age = (as_of - call_date_obj.date()).days
        else:
            age = None
    except Exception:
        age = None

    if age is not None and age > STILL_PROCESSING_DAYS:
        return f"{TERMINAL} no transcript ({age}d-old call, none will appear)"
    return f"{RETRY} no transcript yet (recent call, may still be processing)"


def compute_metrics(utterances: List[Dict]) -> Dict:
    """
    Compute per-speaker talk time + question count + longest monologue.

    Backchannel rule: A run isn't broken by other-speaker interjections
    totaling under 3 seconds, and that time isn't credited to the monologue.
    Without it, an eight-minute monologue reads as twelve short runs every
    time the other party says "mm-hmm."

    Handles timing-unavailable sources (Gong): If any utterance has None
    timestamps, talk_time and longest_monologue metrics are skipped (not
    computed with placeholder values). Question count (text-based) still works.

    Returns:
    {
        'talk_time_seconds': {speaker: seconds, ...},
        'question_count': {speaker: count, ...},
        'longest_monologue_seconds': {speaker: seconds, ...}
    }
    """
    if not utterances:
        return {
            'talk_time_seconds': {},
            'question_count': {},
            'longest_monologue_seconds': {}
        }

    # Check if timing data is available (Gong has None timestamps)
    has_timing = all(
        u.get('start_seconds') is not None and u.get('end_seconds') is not None
        for u in utterances
    )

    talk_time = {}
    question_count = {}

    # Talk time and question count
    for u in utterances:
        speaker = u['speaker']
        text = u['text']

        # Talk time (only if timing available)
        if has_timing:
            duration = u['end_seconds'] - u['start_seconds']
            talk_time[speaker] = talk_time.get(speaker, 0.0) + duration

        # Question count (text-based heuristic — works without timing)
        if text.strip().endswith('?'):
            question_count[speaker] = question_count.get(speaker, 0) + 1

    # Longest monologue (with backchannel rule) — only if timing available
    monologues = {}

    if has_timing:
        current_speaker = None
        current_run_duration = 0.0
        backchannel_buffer = []  # [(speaker, duration), ...]
        BACKCHANNEL_THRESHOLD = 3.0  # seconds

        for u in utterances:
            speaker = u['speaker']
            duration = u['end_seconds'] - u['start_seconds']

            if speaker == current_speaker:
                # Same speaker continues
                current_run_duration += duration
                # Clear any buffered backchannels (they didn't break the run)
                backchannel_buffer = []

            else:
                # Different speaker
                if current_speaker is not None:
                    # Check if this is a backchannel (short interjection)
                    total_backchannel = sum(d for _, d in backchannel_buffer) + duration

                    if total_backchannel < BACKCHANNEL_THRESHOLD:
                        # It's a backchannel - buffer it but don't break the run
                        backchannel_buffer.append((speaker, duration))
                        # Track backchannel speaker's own monologue
                        if duration > monologues.get(speaker, 0.0):
                            monologues[speaker] = duration
                    else:
                        # It's a real speaker change - finalize the current run
                        if current_run_duration > monologues.get(current_speaker, 0.0):
                            monologues[current_speaker] = current_run_duration

                        # Finalize any buffered backchannels
                        for bc_speaker, bc_duration in backchannel_buffer:
                            if bc_duration > monologues.get(bc_speaker, 0.0):
                                monologues[bc_speaker] = bc_duration

                        # Start new run with the interrupting speaker
                        current_speaker = speaker
                        current_run_duration = duration
                        backchannel_buffer = []
                else:
                    # First utterance
                    current_speaker = speaker
                    current_run_duration = duration

        # Finalize last run
        if current_speaker is not None:
            if current_run_duration > monologues.get(current_speaker, 0.0):
                monologues[current_speaker] = current_run_duration

        # Finalize any remaining backchannels
        for bc_speaker, bc_duration in backchannel_buffer:
            if bc_duration > monologues.get(bc_speaker, 0.0):
                monologues[bc_speaker] = bc_duration

    return {
        'talk_time_seconds': talk_time,
        'question_count': question_count,
        'longest_monologue_seconds': monologues
    }


def is_done(quality: str, reason: Optional[str]) -> bool:
    """
    A call_transcripts row is DONE (resume should NOT re-attempt it) when it
    has text, or when it is a TERMINAL empty. A RETRY/pending empty, or an
    absent row, is re-attempted.

    Single authority shared by the backfill's resume set and the tests.

    This is the corrected resume logic: transient failures (rate limits, API
    errors) are written with "retry:" prefix so backfill re-attempts them.
    Terminal empties (old calls that will never have transcripts) get
    "terminal:" prefix so backfill stops wasting API calls on them.

    Args:
        quality: transcript_quality field value
        reason: unavailable_reason field value

    Returns:
        True if the row is done (skip on resume), False if should retry
    """
    if quality != UNAVAILABLE:
        return True
    return bool(reason) and reason.startswith(TERMINAL)


def deduplicate_transcripts(
    transcript_rows: List[Dict],
    priority: List[str] = ['fireflies', 'gong', 'apollo']
) -> List[Dict]:
    """
    Source-priority dedup: keep highest-priority source for each call_id.

    Args:
        transcript_rows: List of transcript rows (from build_transcript_row)
        priority: Source priority order (default: Fireflies > Gong > Apollo)

    Returns:
        Deduplicated list (one row per call_id)
    """
    # Build priority map (lower index = higher priority)
    priority_map = {source: idx for idx, source in enumerate(priority)}

    # Group by call_id
    by_call = {}
    for row in transcript_rows:
        call_id = row['call_id']
        if call_id not in by_call:
            by_call[call_id] = []
        by_call[call_id].append(row)

    # For each call_id, keep highest-priority source
    deduplicated = []
    for call_id, rows in by_call.items():
        # Sort by priority (lowest priority_map value = highest priority)
        rows_sorted = sorted(
            rows,
            key=lambda r: priority_map.get(r['source'], 999)
        )
        deduplicated.append(rows_sorted[0])

    return deduplicated
