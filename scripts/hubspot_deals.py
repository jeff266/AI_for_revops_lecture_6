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
        - overall_score: 0-70 (sum of all 7 components)
        - status: red/yellow/green (from ✅/⚠️/❌ symbols)
        - champion_score: 0-10
        - economic_buyer_score: 0-10
        - summary: 2-sentence summary from "Summary & Recommended Actions"
        """
        import re

        scores = {
            'overall_score': '0',
            'status': 'yellow',
            'champion_score': '0',
            'economic_buyer_score': '0',
            'summary': 'Analysis pending'
        }

        # Extract all component scores using "Score: N/10" pattern
        component_scores = []

        # Component names to search for
        components = [
            'Metrics',
            'Economic Buyer',
            'Decision Criteria',
            'Decision Process',
            'Identify Pain',
            'Champion',
            'Competition'
        ]

        for component in components:
            # Match "Component:\nScore: N/10" pattern (multiline)
            pattern = rf'{re.escape(component)}[:\s]*.*?Score:\s*(\d+)/10'
            match = re.search(pattern, analysis_content, re.DOTALL | re.IGNORECASE)
            if match:
                score = int(match.group(1))
                component_scores.append(score)

                # Save specific component scores
                if component == 'Champion':
                    scores['champion_score'] = str(score)
                elif component == 'Economic Buyer':
                    scores['economic_buyer_score'] = str(score)

        # Calculate overall score as sum of all components (0-70)
        if component_scores:
            scores['overall_score'] = str(sum(component_scores))

        # Extract status from symbols in overall summary
        # Look for ✅ (green), ⚠️ (yellow), ❌ (red)
        identified_count = len(re.findall(r'✅\s*Identified', analysis_content))
        partial_count = len(re.findall(r'⚠️\s*Partial', analysis_content))
        missing_count = len(re.findall(r'❌\s*Not Identified', analysis_content))

        # Determine status based on component identification
        if missing_count >= 4:  # Most components missing
            scores['status'] = 'red'
        elif missing_count >= 2 or partial_count >= 4:  # Some missing or many partial
            scores['status'] = 'yellow'
        elif identified_count >= 5:  # Most identified
            scores['status'] = 'green'

        # Extract summary from "Summary & Recommended Actions" section
        summary_match = re.search(
            r'#+\s*Summary\s*&?\s*Recommended Actions[:\s]*(.*?)(?:\n#+|\Z)',
            analysis_content,
            re.DOTALL | re.IGNORECASE
        )

        if summary_match:
            summary_text = summary_match.group(1).strip()
            # Get first two sentences
            sentences = re.split(r'(?<=[.!?])\s+', summary_text)
            if len(sentences) >= 2:
                scores['summary'] = ' '.join(sentences[:2]).strip()
            elif sentences:
                scores['summary'] = sentences[0].strip()

        return scores

    def upsert_meddicc_note(self, deal_id: str, analysis_content: str, calls_count: int = 0) -> dict:
        """
        Update MEDDICC analysis on a deal by PATCHing deal properties.

        Extracts structured scores from analysis markdown and updates:
        - meddicc_score (0-70)
        - meddicc_status (red/yellow/green)
        - meddicc_last_analyzed (date)
        - meddicc_champion_score (0-10)
        - meddicc_economic_buyer_score (0-10)
        - meddicc_analysis_summary (2-sentence summary)
        """
        today = datetime.now().strftime('%Y-%m-%d')

        # Extract structured scores from analysis
        scores = self._extract_scores_from_analysis(analysis_content)

        # PATCH deal properties with structured scores
        endpoint = f"/crm/v3/objects/deals/{deal_id}"
        properties_data = {
            'properties': {
                'meddicc_score': scores['overall_score'],
                'meddicc_status': scores['status'],
                'meddicc_last_analyzed': today,
                'meddicc_champion_score': scores['champion_score'],
                'meddicc_economic_buyer_score': scores['economic_buyer_score'],
                'meddicc_analysis_summary': scores['summary']
            }
        }

        result = self._patch(endpoint, properties_data)
        print(f"  ✓ Updated deal properties (score: {scores['overall_score']}/70, status: {scores['status']})")
        return result

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
