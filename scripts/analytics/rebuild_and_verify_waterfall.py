#!/usr/bin/env python3
"""
Rebuild waterfall for 2026-08-10 and verify close_date and company_name are present.
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Step 1: Delete old waterfall data
print("Deleting old waterfall data for 2026-08-10...")
sb.table('waterfall_weekly').delete().eq('week_ending', '2026-08-10').execute()
print("✓ Deleted\n")

# Step 2: Recompute waterfall
print("Recomputing waterfall...")
import subprocess
result = subprocess.run(
    ['python', 'scripts/analytics/compute_waterfall.py'],
    capture_output=True,
    text=True
)
print(result.stdout)
if result.stderr:
    print(result.stderr)
if result.returncode != 0:
    print(f"⚠️  Waterfall computation failed with exit code {result.returncode}")
    exit(1)

# Step 3: Verify close_date and company_name are present
print("\n" + "="*70)
print("VERIFICATION: Top 10 deals with company_name and close_date")
print("="*70 + "\n")

query = """
SELECT
  d->>'company_name' as company,
  d->>'change_type' as change,
  d->>'close_date' as close_date,
  (d->>'value')::numeric as value
FROM waterfall_weekly,
     jsonb_array_elements(details) d
WHERE week_ending = '2026-08-10'
ORDER BY (d->>'value')::numeric DESC NULLS LAST
LIMIT 10
"""

result = sb.rpc('exec_sql', {'query': query}).execute()
for row in result.data:
    print(f"{row.get('company', 'N/A')[:30]:30s} "
          f"{row.get('change', 'N/A'):15s} "
          f"{row.get('close_date', 'N/A'):12s} "
          f"${float(row.get('value', 0) or 0):>12,.0f}")

# Step 4: Test Q3 slice query
print("\n" + "="*70)
print("Q3 SLICE (May 1 - Jul 31, 2026)")
print("="*70 + "\n")

q3_query = """
SELECT
  count(*) as deals,
  sum((d->>'value')::numeric) as q3_value
FROM waterfall_weekly,
     jsonb_array_elements(details) d
WHERE week_ending = '2026-08-10'
  AND (d->>'close_date') BETWEEN '2026-05-01'
                             AND '2026-07-31'
"""

result = sb.rpc('exec_sql', {'query': q3_query}).execute()
if result.data:
    row = result.data[0]
    print(f"Deals in Q3: {row.get('deals', 0)}")
    print(f"Q3 Value: ${float(row.get('q3_value', 0) or 0):,.0f}")
else:
    print("No Q3 data found")

print("\n✓ Verification complete")
