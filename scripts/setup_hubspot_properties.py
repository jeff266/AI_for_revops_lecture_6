#!/usr/bin/env python3
"""
One-time setup: creates the per-component MEDDICC/MEDDPICC/SPICED/BANT
properties in HubSpot (N scores + N status + N evidence fields, where
N = number of components in the active methodology).

Idempotent — skips properties that already exist.

Usage: HUBSPOT_API_KEY=... python scripts/setup_hubspot_properties.py
"""

import os
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from utils import get_components, component_key

BASE = "https://api.hubapi.com"
GROUP_NAME = "meddicc_scoring"


def get_headers():
    return {
        "Authorization": f"Bearer {os.environ['HUBSPOT_API_KEY']}",
        "Content-Type": "application/json"
    }


def ensure_group():
    """Create the MEDDICC Scoring property group if needed."""
    resp = requests.get(
        f"{BASE}/crm/v3/properties/deals/groups/{GROUP_NAME}",
        headers=get_headers()
    )
    if resp.status_code == 200:
        print(f"Group '{GROUP_NAME}' already exists")
        return
    resp = requests.post(
        f"{BASE}/crm/v3/properties/deals/groups",
        headers=get_headers(),
        json={
            "name": GROUP_NAME,
            "label": "MEDDICC Scoring",
            "displayOrder": 10
        }
    )
    resp.raise_for_status()
    print(f"Created group '{GROUP_NAME}'")


def get_existing_props() -> set:
    resp = requests.get(
        f"{BASE}/crm/v3/properties/deals",
        params={"limit": 1000},
        headers=get_headers()
    )
    resp.raise_for_status()
    return {p["name"] for p in resp.json().get("results", [])}


def create_property(name, label, field_type, prop_type,
                    description="", options=None):
    body = {
        "name": name,
        "label": label,
        "type": prop_type,
        "fieldType": field_type,
        "groupName": GROUP_NAME,
        "description": description,
        "hasUniqueValue": False,
    }
    if options:
        body["options"] = options
    resp = requests.post(
        f"{BASE}/crm/v3/properties/deals",
        headers=get_headers(),
        json=body
    )
    resp.raise_for_status()
    return resp.json()


def main():
    # Build component list from config (methodology-agnostic)
    components = get_components()
    component_pairs = [(component_key(label), label) for label in components]

    print(f"\nSetting up HubSpot properties for {len(components)} components:")
    for key, label in component_pairs:
        print(f"  - {label} ({key})")
    print()

    ensure_group()
    existing = get_existing_props()
    created, skipped = [], []

    for key, label in component_pairs:
        # Score property (number, 1-10)
        score_name = f"meddicc_{key}_score"
        if score_name not in existing:
            create_property(
                name=score_name,
                label=f"{label} Score",
                field_type="number",
                prop_type="number",
                description=f"MEDDICC {label} score (1-10). "
                            f"Derived from cumulative call history."
            )
            created.append(score_name)
            print(f"  Created: {score_name}")
        else:
            skipped.append(score_name)
            print(f"  Exists:  {score_name}")

        # Status property (enum: identified/partial/unknown)
        status_name = f"meddicc_{key}_status"
        if status_name not in existing:
            create_property(
                name=status_name,
                label=f"{label} Status",
                field_type="select",
                prop_type="enumeration",
                description=f"MEDDICC {label} qualification status.",
                options=[
                    {"label": "Identified", "value": "identified",
                     "displayOrder": 0, "hidden": False},
                    {"label": "Partial",    "value": "partial",
                     "displayOrder": 1, "hidden": False},
                    {"label": "Unknown",    "value": "unknown",
                     "displayOrder": 2, "hidden": False},
                ]
            )
            created.append(status_name)
            print(f"  Created: {status_name}")
        else:
            skipped.append(status_name)

        # Rationale property (text, max 1000 chars)
        rationale_name = f"meddicc_{key}_rationale"
        if rationale_name not in existing:
            create_property(
                name=rationale_name,
                label=f"{label} Evidence",
                field_type="textarea",
                prop_type="string",
                description=f"Evidence from call history supporting "
                            f"the {label} score. Auto-updated nightly."
            )
            created.append(rationale_name)
            print(f"  Created: {rationale_name}")
        else:
            skipped.append(rationale_name)
            print(f"  Exists:  {rationale_name}")

    print(f"\nDone. Created {len(created)}, skipped {len(skipped)}.")
    print("Created:", created)


if __name__ == "__main__":
    main()
