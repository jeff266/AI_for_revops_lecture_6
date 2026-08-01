"""
HubSpot Deals Client for MEDDICC Agent

Manages active deals and deal notes for MEDDICC analysis.
"""
import os
import sys
import requests
from typing import List, Dict, Optional
from datetime import datetime


class HubSpotDealsClient:
    """Client for HubSpot Deals API."""

    BASE_URL = "https://api.hubapi.com"

    # Pipeline IDs
    SALES_PIPELINE = "default"
    RENEWAL_PIPELINE = "866608541"

    # Closed stages to exclude
    CLOSED_STAGES = ['closedwon', 'closedlost']

    def __init__(self, api_key: str = None):
        """Initialize with API key."""
        self.api_key = api_key or os.getenv("HUBSPOT_API_KEY")
        if not self.api_key:
            raise ValueError("HUBSPOT_API_KEY environment variable not set")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Execute GET request."""
        response = self.session.get(f"{self.BASE_URL}{endpoint}", params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict = None) -> dict:
        """Execute POST request."""
        response = self.session.post(f"{self.BASE_URL}{endpoint}", json=data)
        response.raise_for_status()
        return response.json()

    def _patch(self, endpoint: str, data: dict = None) -> dict:
        """Execute PATCH request."""
        response = self.session.patch(f"{self.BASE_URL}{endpoint}", json=data)
        response.raise_for_status()
        return response.json()

    def get_active_deals(self) -> List[dict]:
        """
        Get all active deals (not Closed Won/Lost).

        Returns deals with company associations and key properties.
        """
        endpoint = "/crm/v3/objects/deals/search"

        # Build filter: exclude Closed Won and Closed Lost
        body = {
            'filterGroups': [{
                'filters': [
                    {'propertyName': 'dealstage', 'operator': 'NEQ', 'value': 'closedwon'},
                    {'propertyName': 'dealstage', 'operator': 'NEQ', 'value': 'closedlost'}
                ]
            }],
            'properties': [
                'dealname',
                'dealstage',
                'pipeline',
                'closedate',
                'incremental_arr',
                'amount',
                'hubspot_owner_id',
                'dealtype',
                'createdate',
                'last_meddicc_analysis_date'
            ],
            'sorts': [
                {'propertyName': 'closedate', 'direction': 'ASCENDING'}  # Earliest close date first
            ],
            'limit': 100
        }

        all_deals = []
        after = None

        while True:
            if after:
                body['after'] = after

            response = self._post(endpoint, body)
            results = response.get('results', [])
            all_deals.extend(results)

            paging = response.get('paging', {})
            after = paging.get('next', {}).get('after')

            if not after:
                break

        return all_deals

    def get_deal_company(self, deal_id: str) -> Optional[dict]:
        """Get associated company for a deal."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}/associations/companies"

        try:
            response = self._get(endpoint)
            associations = response.get('results', [])

            if not associations:
                return None

            company_id = associations[0].get('id')

            # Get company details
            company_endpoint = f"/crm/v3/objects/companies/{company_id}"
            company_response = self._get(
                company_endpoint,
                params={'properties': ['name', 'domain', 'numberofemployees', 'industry']}
            )

            return company_response

        except Exception as e:
            print(f"Error getting company for deal {deal_id}: {e}")
            return None

    def get_deal_contacts(self, deal_id: str) -> List[dict]:
        """Get associated contacts for a deal."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}/associations/contacts"

        try:
            response = self._get(endpoint)
            contact_associations = response.get('results', [])

            contacts = []
            for assoc in contact_associations[:10]:  # Limit to 10 contacts
                contact_id = assoc.get('id')
                contact_endpoint = f"/crm/v3/objects/contacts/{contact_id}"
                contact_response = self._get(
                    contact_endpoint,
                    params={'properties': ['firstname', 'lastname', 'email', 'jobtitle']}
                )
                contacts.append(contact_response)

            return contacts

        except Exception as e:
            print(f"Error getting contacts for deal {deal_id}: {e}")
            return []

    def get_deal_notes(self, deal_id: str) -> List[dict]:
        """Get notes associated with a deal."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}/associations/notes"

        try:
            response = self._get(endpoint)
            note_associations = response.get('results', [])

            notes = []
            for assoc in note_associations:
                note_id = assoc.get('id')
                note_endpoint = f"/crm/v3/objects/notes/{note_id}"
                note_response = self._get(note_endpoint, params={'properties': ['hs_note_body', 'hs_timestamp']})
                notes.append(note_response)

            return notes

        except Exception as e:
            print(f"Error getting notes for deal {deal_id}: {e}")
            return []

    def find_meddicc_note(self, deal_id: str) -> Optional[dict]:
        """Find existing MEDDICC analysis note for a deal."""
        notes = self.get_deal_notes(deal_id)

        for note in notes:
            body = note.get('properties', {}).get('hs_note_body', '')
            if '## MEDDICC Analysis' in body or 'MEDDICC Analysis' in body:
                return note

        return None

    def create_deal_note(self, deal_id: str, note_content: str) -> dict:
        """Create a new note on a deal."""
        endpoint = "/crm/v3/objects/notes"

        data = {
            'properties': {
                'hs_note_body': note_content,
                'hs_timestamp': int(datetime.now().timestamp() * 1000)
            }
        }

        # Create note
        note_response = self._post(endpoint, data)
        note_id = note_response.get('id')

        # Associate with deal
        assoc_endpoint = f"/crm/v3/objects/notes/{note_id}/associations/deals/{deal_id}/note_to_deal"
        self._patch(assoc_endpoint, {})

        return note_response

    def update_deal_note(self, note_id: str, note_content: str) -> dict:
        """Update an existing note."""
        endpoint = f"/crm/v3/objects/notes/{note_id}"

        data = {
            'properties': {
                'hs_note_body': note_content,
                'hs_timestamp': int(datetime.now().timestamp() * 1000)
            }
        }

        return self._patch(endpoint, data)

    def update_deal_property(self, deal_id: str, property_name: str, value: str) -> dict:
        """Update a single deal property."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}"

        data = {
            'properties': {
                property_name: value
            }
        }

        return self._patch(endpoint, data)

    def _extract_scores_from_analysis(self, analysis_content: str) -> dict:
        """
        Extract structured scores from MEDDICC analysis markdown.

        Returns dict with:
        - overall_score: 0-100
        - status: red/yellow/green
        - champion_score: 0-10
        - economic_buyer_score: 0-10
        - summary: 2-sentence summary
        """
        import re

        scores = {
            'overall_score': '0',
            'status': 'yellow',
            'champion_score': '0',
            'economic_buyer_score': '0',
            'summary': 'Analysis pending'
        }

        # Extract overall score (look for patterns like "Score: 15/100" or "Overall: 15")
        score_match = re.search(r'(?:Score|Overall)[:\s]+(\d+)(?:/100)?', analysis_content, re.IGNORECASE)
        if score_match:
            scores['overall_score'] = score_match.group(1)

        # Extract status (look for red/yellow/green)
        if re.search(r'\b(red|critical|failing)\b', analysis_content, re.IGNORECASE):
            scores['status'] = 'red'
        elif re.search(r'\b(green|strong|passing)\b', analysis_content, re.IGNORECASE):
            scores['status'] = 'green'

        # Extract Champion score (look for "Champion: 7" or "Champion Score: 7/10")
        champion_match = re.search(r'Champion[:\s]+(\d+)(?:/10)?', analysis_content, re.IGNORECASE)
        if champion_match:
            scores['champion_score'] = champion_match.group(1)

        # Extract Economic Buyer score
        eb_match = re.search(r'Economic\s+Buyer[:\s]+(\d+)(?:/10)?', analysis_content, re.IGNORECASE)
        if eb_match:
            scores['economic_buyer_score'] = eb_match.group(1)

        # Extract summary (first 2 sentences or first paragraph)
        lines = [l.strip() for l in analysis_content.split('\n') if l.strip() and not l.strip().startswith('#')]
        if lines:
            # Get first non-header paragraph, limit to ~250 chars
            summary_text = lines[0][:250]
            scores['summary'] = summary_text

        return scores

    def upsert_meddicc_note(self, deal_id: str, analysis_content: str, calls_count: int = 0) -> dict:
        """
        Create or update MEDDICC analysis on a deal using TWO mechanisms:

        1. PATCH deal properties with structured scores
        2. POST timeline event with full analysis narrative

        Also updates the legacy note for backwards compatibility.
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
        today = datetime.now().strftime('%Y-%m-%d')

        # Extract structured scores from analysis
        scores = self._extract_scores_from_analysis(analysis_content)

        # MECHANISM 1: Update deal properties with structured scores
        try:
            endpoint = f"/crm/v3/objects/deals/{deal_id}"
            properties_data = {
                'properties': {
                    'meddicc_score': scores['overall_score'],
                    'meddicc_status': scores['status'],
                    'meddicc_last_analyzed': today,
                    'meddicc_champion_score': scores['champion_score'],
                    'meddicc_economic_buyer_score': scores['economic_buyer_score'],
                    'meddicc_analysis_summary': scores['summary'],
                    'last_meddicc_analysis_date': today  # Keep for backwards compatibility
                }
            }
            self._patch(endpoint, properties_data)
            print(f"  ✓ Updated deal properties (score: {scores['overall_score']}, status: {scores['status']})")
        except Exception as e:
            print(f"  ⚠️  Failed to update deal properties: {e}")

        # MECHANISM 2: Create timeline event with full analysis
        try:
            self.create_timeline_event(
                deal_id,
                analysis_content,
                f"{scores['overall_score']}/100"
            )
        except Exception as e:
            print(f"  ⚠️  Timeline event error: {e}")

        # LEGACY: Also update note for backwards compatibility
        formatted_note = f"""## MEDDICC Analysis
**Generated:** {timestamp}
**Based on:** {calls_count} recorded calls
**Score:** {scores['overall_score']}/100 ({scores['status']})

{analysis_content}

---
*Auto-generated by MEDDICC Agent*
"""

        try:
            existing_note = self.find_meddicc_note(deal_id)
            if existing_note:
                note_id = existing_note.get('id')
                result = self.update_deal_note(note_id, formatted_note)
            else:
                result = self.create_deal_note(deal_id, formatted_note)
            return result
        except Exception as e:
            print(f"  ⚠️  Note update failed (non-critical): {e}")
            return {}

    def get_deal_context(self, deal_id: str) -> dict:
        """
        Get full deal context for MEDDICC analysis.

        Returns company info, contacts, deal properties.
        """
        # Get deal properties
        endpoint = f"/crm/v3/objects/deals/{deal_id}"
        deal = self._get(
            endpoint,
            params={'properties': ['dealname', 'dealstage', 'incremental_arr', 'closedate', 'pipeline']}
        )

        # Get company
        company = self.get_deal_company(deal_id)

        # Get contacts
        contacts = self.get_deal_contacts(deal_id)

        return {
            'deal': deal,
            'company': company,
            'contacts': contacts
        }

    def setup_hubspot_properties(self) -> bool:
        """
        Create custom MEDDICC properties in HubSpot if they don't exist.

        Creates:
        - meddicc_score (Number)
        - meddicc_status (Single-line text)
        - meddicc_last_analyzed (Date)
        - meddicc_champion_score (Number)
        - meddicc_economic_buyer_score (Number)
        - meddicc_analysis_summary (Multi-line text)
        """
        endpoint = "/crm/v3/properties/deals"

        properties_to_create = [
            {
                "name": "meddicc_score",
                "label": "MEDDICC Score",
                "type": "number",
                "fieldType": "number",
                "groupName": "dealinformation",
                "description": "Overall MEDDICC qualification score (0-100)"
            },
            {
                "name": "meddicc_status",
                "label": "MEDDICC Status",
                "type": "string",
                "fieldType": "text",
                "groupName": "dealinformation",
                "description": "MEDDICC health status: red/yellow/green"
            },
            {
                "name": "meddicc_last_analyzed",
                "label": "MEDDICC Last Analyzed",
                "type": "date",
                "fieldType": "date",
                "groupName": "dealinformation",
                "description": "Date of most recent MEDDICC analysis"
            },
            {
                "name": "meddicc_champion_score",
                "label": "MEDDICC Champion Score",
                "type": "number",
                "fieldType": "number",
                "groupName": "dealinformation",
                "description": "Champion component score (0-10)"
            },
            {
                "name": "meddicc_economic_buyer_score",
                "label": "MEDDICC Economic Buyer Score",
                "type": "number",
                "fieldType": "number",
                "groupName": "dealinformation",
                "description": "Economic Buyer component score (0-10)"
            },
            {
                "name": "meddicc_analysis_summary",
                "label": "MEDDICC Analysis Summary",
                "type": "string",
                "fieldType": "textarea",
                "groupName": "dealinformation",
                "description": "2-sentence summary of MEDDICC analysis"
            }
        ]

        created_count = 0
        for prop in properties_to_create:
            try:
                self._post(endpoint, prop)
                created_count += 1
                print(f"  ✓ Created property: {prop['name']}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 409:
                    # Property already exists
                    print(f"  → Property exists: {prop['name']}")
                else:
                    print(f"  ⚠️  Error creating {prop['name']}: {e}")

        return True

    def setup_timeline_template(self) -> Optional[str]:
        """
        Create timeline event template for MEDDICC analysis.

        Returns the template ID if successful.
        """
        endpoint = "/crm/v3/timeline/event-templates"

        # Check if template already exists by trying to create it
        template_data = {
            "name": "MEDDICC Analysis",
            "objectType": "deals",
            "headerTemplate": "MEDDICC Analysis - {{score}}",
            "detailTemplate": "{{analysis}}",
            "tokens": [
                {
                    "name": "score",
                    "label": "MEDDICC Score",
                    "type": "string"
                },
                {
                    "name": "analysis",
                    "label": "Full Analysis",
                    "type": "string"
                }
            ]
        }

        try:
            response = self._post(endpoint, template_data)
            template_id = response.get('id')
            print(f"  ✓ Created timeline template: {template_id}")
            return template_id
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:
                # Template already exists - try to get it
                print(f"  → Timeline template already exists")
                # Note: We'll need to store the template ID in config or env
                return os.getenv("HUBSPOT_TIMELINE_TEMPLATE_ID")
            else:
                print(f"  ⚠️  Error creating timeline template: {e}")
                return None

    def create_timeline_event(self, deal_id: str, analysis_content: str, score: str = "N/A") -> bool:
        """
        Create a timeline event for MEDDICC analysis.

        Args:
            deal_id: HubSpot deal ID
            analysis_content: Full analysis markdown
            score: MEDDICC score string
        """
        template_id = os.getenv("HUBSPOT_TIMELINE_TEMPLATE_ID")
        if not template_id:
            print("  ⚠️  Timeline template ID not configured, skipping timeline event")
            return False

        endpoint = "/crm/v3/timeline/events"

        event_data = {
            "eventTemplateId": template_id,
            "objectId": deal_id,
            "tokens": {
                "score": score,
                "analysis": analysis_content
            },
            "timestamp": int(datetime.now().timestamp() * 1000)
        }

        try:
            self._post(endpoint, event_data)
            print(f"  ✓ Created timeline event")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"  ⚠️  Timeline event failed: {e}")
            return False

    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            endpoint = "/crm/v3/objects/deals"
            response = self._get(endpoint, params={'limit': 1})
            return 'results' in response
        except Exception as e:
            print(f"Connection failed: {e}")
            return False


def get_hubspot_deals_client(api_key: str = None) -> HubSpotDealsClient:
    """Get configured HubSpot Deals client."""
    return HubSpotDealsClient(api_key)


if __name__ == "__main__":
    # Test HubSpot connection
    client = get_hubspot_deals_client()

    print("Testing HubSpot connection...")
    if not client.test_connection():
        print("❌ Failed to connect")
        sys.exit(1)

    print("✓ Connected to HubSpot")

    # Setup custom properties (run once, idempotent)
    print("\nSetting up custom MEDDICC properties...")
    client.setup_hubspot_properties()

    # Setup timeline template (run once, idempotent)
    print("\nSetting up timeline event template...")
    template_id = client.setup_timeline_template()
    if template_id:
        print(f"  Template ID: {template_id}")
        print(f"  Set HUBSPOT_TIMELINE_TEMPLATE_ID={template_id} in your environment")

    # Get active deals
    print("\nFetching active deals...")
    deals = client.get_active_deals()
    print(f"Found {len(deals)} active deals")

    if deals:
        # Test with first deal
        test_deal = deals[0]
        deal_id = test_deal.get('id')
        deal_name = test_deal.get('properties', {}).get('dealname', 'Unknown')

        print(f"\nTesting with deal: {deal_name}")

        # Get deal context
        context = client.get_deal_context(deal_id)
        company = context.get('company')
        if company:
            company_name = company.get('properties', {}).get('name', 'Unknown')
            print(f"  Company: {company_name}")

        contacts = context.get('contacts', [])
        print(f"  Contacts: {len(contacts)}")

        # Check for existing MEDDICC note
        meddicc_note = client.find_meddicc_note(deal_id)
        if meddicc_note:
            print(f"  ✓ Has existing MEDDICC note")
        else:
            print(f"  ✗ No MEDDICC note yet")
