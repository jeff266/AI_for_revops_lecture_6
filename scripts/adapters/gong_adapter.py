"""
Gong API Adapter

Implements the same interface as fireflies_client.py but reads from Gong API.
Used by etl_calls.py when config/client.yaml sets call_tools.primary = gong.

Gong provides richer structured data than Fireflies:
- Speaker-attributed transcript turns
- Talk time ratios per speaker
- Topic detection (pricing, next steps, competition, pain)
- Sentiment signals
- Action items and next steps extracted by Gong's AI
- Deal risk signals

This produces better formatted summaries for MEDDICC analysis.
"""

import os
import base64
import requests
from datetime import datetime
from typing import List, Optional, Dict


class GongAdapter:
    """
    Gong call intelligence adapter.

    Authentication: Basic auth with Access Key + Secret (base64 encoded)
    API docs: https://gong.app.gong.io/settings/api/documentation
    """

    # API access level for this client
    # basic: metadata only (title, date, duration, participants)
    # rich: transcripts, topics, action items available
    # Check with Gong admin: requires Technical Admin role
    # and Transcription feature enabled on account
    ACCESS_LEVEL = 'basic'

    @classmethod
    def enable_rich_access(cls):
        """Enable rich data mode (transcripts, topics, action items)."""
        cls.ACCESS_LEVEL = 'rich'

    def __init__(self):
        """Initialize Gong adapter with API credentials."""
        key = os.getenv('GONG_ACCESS_KEY')
        secret = os.getenv('GONG_ACCESS_KEY_SECRET')

        if not key or not secret:
            raise ValueError(
                'GONG_ACCESS_KEY and GONG_ACCESS_KEY_SECRET environment '
                'variables are required for Gong adapter'
            )

        # Basic auth: base64 encode "key:secret"
        token = base64.b64encode(f'{key}:{secret}'.encode()).decode()

        self.headers = {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json'
        }
        self.base_url = 'https://api.gong.io/v2'

    def search_by_company(self, company_name: str,
                          since_date: Optional[datetime] = None) -> List[Dict]:
        """
        Fetch calls mentioning this company name with rich structured data.

        Uses /v2/calls to get call list, then /v2/calls/extensive to batch
        fetch rich data (topics, action items, talk time, etc.).

        Args:
            company_name: Company to search for
            since_date: Only return calls after this date

        Returns:
            List of enriched call dicts with full Gong intelligence data
        """
        # STEP 1: Get call list with basic metadata
        params = {}
        if since_date:
            params['fromDateTime'] = since_date.isoformat()

        response = requests.get(
            f'{self.base_url}/calls',
            headers=self.headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        calls = response.json().get('calls', [])

        # STEP 2: Filter by company name in title
        company_lower = company_name.lower()
        matched = [
            call for call in calls
            if company_lower in call.get('title', '').lower()
        ]

        if not matched:
            return []

        # STEP 3: Batch fetch rich data using /v2/calls/extensive
        # Max 20 calls per request
        call_ids = [c['id'] for c in matched]
        enriched = []

        for i in range(0, len(call_ids), 20):
            batch_ids = call_ids[i:i+20]

            try:
                extensive_resp = requests.post(
                    f'{self.base_url}/calls/extensive',
                    headers=self.headers,
                    json={'filter': {'callIds': batch_ids}},
                    timeout=30
                )

                if extensive_resp.status_code == 200:
                    batch_calls = extensive_resp.json().get('calls', [])
                    enriched.extend(batch_calls)
            except Exception as e:
                print(f'Warning: Failed to fetch extensive data for batch: {e}')
                continue

        # STEP 4: Merge basic metadata + rich data
        rich_by_id = {
            c.get('metaData', {}).get('id'): c
            for c in enriched
        }

        results = []
        for call in matched:
            call_id = call['id']

            if call_id in rich_by_id:
                rich = rich_by_id[call_id]
                content = rich.get('content', {})

                # Flatten into format expected by format_summary_for_meddicc()
                merged = {
                    'id': call_id,
                    'title': call.get('title', ''),
                    'started': call.get('started', ''),
                    'duration': call.get('duration', 0),
                    'brief': content.get('brief', ''),
                    'topics': [t.get('name', '') for t in content.get('topics', [])],
                    'keyPoints': content.get('keyPoints', {}),
                    'parties': rich.get('parties', []),
                }
                results.append(merged)
            else:
                # Fallback to basic data if extensive fetch failed
                results.append({
                    'id': call_id,
                    'title': call.get('title', ''),
                    'started': call.get('started', ''),
                    'duration': call.get('duration', 0),
                    'brief': '',
                    'topics': [],
                    'keyPoints': {},
                    'parties': [],
                })

        return results

    def format_summary_for_meddicc(self, call: Dict) -> str:
        """
        Format a Gong call dict into a MEDDICC-ready summary.

        Uses Gong's structured data:
        - brief: AI-generated summary
        - topics: Detected conversation topics
        - keyPoints: Action items and next steps
        - parties: Participants with talk time percentages

        Args:
            call: Call dict from Gong API

        Returns:
            Formatted summary string for MEDDICC context builder
        """
        title = call.get('title', 'Untitled')
        started = str(call.get('started', ''))[:10]  # YYYY-MM-DD
        duration = round((call.get('duration') or 0) / 60, 1)  # Convert to minutes

        if self.ACCESS_LEVEL == 'basic':
            # Extract participant names from title if possible
            # Gong titles are often "Prospect Name and Rep Name"
            return (
                f"# {title}\n"
                f"Date: {started} | Duration: {duration}m\n\n"
                f"## Note\n"
                f"Full transcript not available via current "
                f"API access level. Call recorded in Gong — "
                f"contact Gong admin to enable transcript API "
                f"access (Technical Admin role required).\n\n"
                f"## Call Activity\n"
                f"A {duration}-minute call took place on "
                f"{started}. Participants visible in title: "
                f"{title}."
            )

        # Rich path (when ACCESS_LEVEL = 'rich')
        brief = call.get('brief', '')

        # Extract Gong's structured insights
        topics = call.get('topics', [])
        key_points = call.get('keyPoints', {})
        action_items = key_points.get('actionItems', [])
        next_steps = key_points.get('nextSteps', [])

        # Talk time analysis
        parties = call.get('parties', [])
        talk_time_lines = []
        for party in parties:
            name = party.get('name', 'Unknown')
            affiliation = party.get('affiliation', '')
            talk_time = party.get('talkTime', {})
            talk_pct = talk_time.get('percentage', 0)
            talk_time_lines.append(
                f'  {name} ({affiliation}): {talk_pct:.0f}%'
            )

        # Build formatted summary
        sections = [
            f'# {title}',
            f'Date: {started} | Duration: {duration}m'
        ]

        if brief:
            sections.extend(['', '## Summary', brief])

        if topics:
            sections.extend(['', '## Topics Discussed'])
            sections.extend([f'- {topic}' for topic in topics])

        if action_items:
            sections.extend(['', '## Action Items'])
            sections.extend([f'- {item}' for item in action_items])

        if next_steps:
            sections.extend(['', '## Next Steps'])
            sections.extend([f'- {step}' for step in next_steps])

        if talk_time_lines:
            sections.extend(['', '## Talk Time'])
            sections.extend(talk_time_lines)

        return '\n'.join(sections)

    def get_transcript(self, call_id: str) -> str:
        """
        Fetch full transcript for a specific call.

        Returns speaker-attributed text with each sentence on a new line.

        Args:
            call_id: Gong call ID

        Returns:
            Full transcript as "Speaker: text" format
        """
        response = requests.get(
            f'{self.base_url}/calls/{call_id}/transcript',
            headers=self.headers,
            timeout=30
        )

        if response.status_code == 404:
            return ''

        response.raise_for_status()

        # Gong returns transcript as array of sentences with speaker attribution
        sentences = response.json().get('callTranscripts', [])
        lines = []

        for sentence in sentences:
            speaker = sentence.get('speakerName', 'Unknown')
            text = sentence.get('sentence', '')
            if text.strip():
                lines.append(f'{speaker}: {text}')

        return '\n'.join(lines)

    def get_calls(self, limit: int = 100, skip: int = 0) -> List[Dict]:
        """
        Get recent calls with rich structured data.

        Uses /v2/calls to get call list, then /v2/calls/extensive to batch
        fetch rich data for all calls.

        Args:
            limit: Number of calls to return
            skip: Number of calls to skip (for pagination)

        Returns:
            List of enriched call dicts with full Gong intelligence data
        """
        # STEP 1: Get call list with basic metadata
        response = requests.get(
            f'{self.base_url}/calls',
            headers=self.headers,
            params={'limit': limit},
            timeout=30
        )
        response.raise_for_status()

        calls = response.json().get('calls', [])

        if not calls:
            return []

        # STEP 2: Batch fetch rich data using /v2/calls/extensive
        # Max 20 calls per request
        call_ids = [c['id'] for c in calls]
        enriched = []

        for i in range(0, len(call_ids), 20):
            batch_ids = call_ids[i:i+20]

            try:
                extensive_resp = requests.post(
                    f'{self.base_url}/calls/extensive',
                    headers=self.headers,
                    json={'filter': {'callIds': batch_ids}},
                    timeout=30
                )

                if extensive_resp.status_code == 200:
                    batch_calls = extensive_resp.json().get('calls', [])
                    enriched.extend(batch_calls)
            except Exception as e:
                print(f'Warning: Failed to fetch extensive data for batch: {e}')
                continue

        # STEP 3: Merge basic metadata + rich data
        rich_by_id = {
            c.get('metaData', {}).get('id'): c
            for c in enriched
        }

        results = []
        for call in calls:
            call_id = call['id']

            if call_id in rich_by_id:
                rich = rich_by_id[call_id]
                content = rich.get('content', {})

                # Flatten into format expected by format_summary_for_meddicc()
                merged = {
                    'id': call_id,
                    'title': call.get('title', ''),
                    'started': call.get('started', ''),
                    'duration': call.get('duration', 0),
                    'brief': content.get('brief', ''),
                    'topics': [t.get('name', '') for t in content.get('topics', [])],
                    'keyPoints': content.get('keyPoints', {}),
                    'parties': rich.get('parties', []),
                }
                results.append(merged)
            else:
                # Fallback to basic data if extensive fetch failed
                results.append({
                    'id': call_id,
                    'title': call.get('title', ''),
                    'started': call.get('started', ''),
                    'duration': call.get('duration', 0),
                    'brief': '',
                    'topics': [],
                    'keyPoints': {},
                    'parties': [],
                })

        return results
