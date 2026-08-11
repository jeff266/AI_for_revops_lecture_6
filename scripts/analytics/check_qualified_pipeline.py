#!/usr/bin/env python3
"""
Check Q3 pipeline by qualification level in Supabase.
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("="*70)
print("Q3 2026 Pipeline by Qualification Level")
print("="*70)

# Query 1: Qualified pipeline (highest_stage_order_reached >= 2)
result1 = sb.table('deals')\
    .select('deal_value')\
    .eq('deal_status', 'active')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .gte('highest_stage_order_reached', 2)\
    .execute()

count1 = len(result1.data)
value1 = sum(float(d.get('deal_value') or 0) for d in result1.data)

print(f"\nQualified Q3 Pipeline (highest_stage_order_reached >= 2):")
print(f"  Count: {count1}")
print(f"  Value: ${value1:,.2f}")

# Query 2: All pipeline including Meeting Set (highest_stage_order_reached >= 0)
result2 = sb.table('deals')\
    .select('deal_value')\
    .eq('deal_status', 'active')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .gte('highest_stage_order_reached', 0)\
    .execute()

count2 = len(result2.data)
value2 = sum(float(d.get('deal_value') or 0) for d in result2.data)

print(f"\nAll Q3 Pipeline including Meeting Set (highest_stage_order_reached >= 0):")
print(f"  Count: {count2}")
print(f"  Value: ${value2:,.2f}")

# Difference
meeting_set_count = count2 - count1
meeting_set_value = value2 - value1

print(f"\nMeeting Set Pipeline (difference):")
print(f"  Count: {meeting_set_count}")
print(f"  Value: ${meeting_set_value:,.2f}")

print(f"\n{'='*70}")
print("Summary:")
print("="*70)
print(f"HubSpot screenshot shows:        $7,798,832.45")
print(f"Qualified pipeline (excl MS):    ${value1:,.2f}")
print(f"All pipeline (incl MS):          ${value2:,.2f}")
print(f"\nDifference from HubSpot (qualified): ${value1 - 7798832.45:,.2f}")
print(f"Difference from HubSpot (all):       ${value2 - 7798832.45:,.2f}")
