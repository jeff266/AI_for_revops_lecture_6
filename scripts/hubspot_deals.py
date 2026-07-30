"""
HubSpot Deals Client for MEDDICC Agent

Manages active deals and deal notes for MEDDICC analysis.
"""
import os
import sys
import requests
from typing import List, Dict, Optional
from datetime import datetime

# Add parent revops-metrics to path
sys.path.insert(0, '/Users/jeffignacio/GrowthBook/revops-metrics')


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
        self.api_key = api_key or os.getenv("HUBSPOT_API_KEY", "pat-na1-7817798e-3dfc-426d-aaa9-f9ed91d90b32")
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

    def upsert_meddicc_note(self, deal_id: str, analysis_content: str, calls_count: int = 0) -> dict:
        """
        Create or update MEDDICC analysis note on a deal.

        Replaces existing MEDDICC note if found, otherwise creates new one.
        Also updates last_meddicc_analysis_date property.
        """
        # Format note with header
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
        formatted_note = f"""## MEDDICC Analysis
**Generated:** {timestamp}
**Based on:** {calls_count} recorded calls

{analysis_content}

---
*Auto-generated by MEDDICC Agent*
"""

        # Check for existing MEDDICC note
        existing_note = self.find_meddicc_note(deal_id)

        if existing_note:
            note_id = existing_note.get('id')
            result = self.update_deal_note(note_id, formatted_note)
        else:
            result = self.create_deal_note(deal_id, formatted_note)

        # Update last analysis date property
        today = datetime.now().strftime('%Y-%m-%d')
        self.update_deal_property(deal_id, 'last_meddicc_analysis_date', today)

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
