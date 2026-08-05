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
        Fetch calls mentioning this company name.

        Uses /v2/calls with date filter, then filters by company name
        in title or parties.

        Args:
            company_name: Company to search for
            since_date: Only return calls after this date

        Returns:
            List of call dicts from Gong API
        """
        params = {}
        if since_date:
            # Gong expects ISO 8601 format
            params['fromDateTime'] = since_date.isoformat()

        # Fetch calls from Gong
        response = requests.get(
            f'{self.base_url}/calls',
            headers=self.headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        calls = response.json().get('calls', [])

        # Filter by company name in title
        # Gong call titles vary by workspace settings but usually include company
        company_lower = company_name.lower()
        matched = [
            call for call in calls
            if company_lower in call.get('title', '').lower()
        ]

        return matched

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
        Get recent calls with pagination.

        Args:
            limit: Number of calls to return
            skip: Number of calls to skip (for pagination)

        Returns:
            List of call dicts
        """
        # Gong uses cursor-based pagination, not offset
        # For now, implement basic fetching
        response = requests.get(
            f'{self.base_url}/calls',
            headers=self.headers,
            params={'limit': limit},
            timeout=30
        )
        response.raise_for_status()

        return response.json().get('calls', [])
