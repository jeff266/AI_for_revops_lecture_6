#!/usr/bin/env python3
"""
Check actual Q3 sales pipeline vs what waterfall showed.
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Q3 2026 = May 1 - Jul 31, 2026
result = sb.table('deals').select('deal_id, company_name, close_date, deal_value, deal_status, stage').gte('close_date', '2026-05-01').lte('close_date', '2026-07-31').execute()

deals = result.data
open_deals = [d for d in deals if d.get('deal_status') in ['active', 'prospective', None]]
closed_deals = [d for d in deals if d.get('deal_status') in ['won', 'lost']]

open_value = sum(float(d.get('deal_value') or 0) for d in open_deals)
closed_value = sum(float(d.get('deal_value') or 0) for d in closed_deals)
total_value = sum(float(d.get('deal_value') or 0) for d in deals)

print(f'Q3 2026 (May 1 - Jul 31) Analysis:')
print(f'')
print(f'Open Pipeline:   {len(open_deals):3d} deals  ${open_value:>12,.0f}')
print(f'Closed (W/L):    {len(closed_deals):3d} deals  ${closed_value:>12,.0f}')
print(f'                 ---           --------------')
print(f'Total:           {len(deals):3d} deals  ${total_value:>12,.0f}')
print(f'')
print(f'Top 10 open Q3 deals by value:')
open_deals.sort(key=lambda x: float(x.get('deal_value') or 0), reverse=True)
for d in open_deals[:10]:
    company = (d.get('company_name') or 'Unknown')[:35]
    value = float(d.get('deal_value') or 0)
    close = d.get('close_date') or 'N/A'
    stage = (d.get('stage') or 'N/A')[:20]
    print(f'  {company:35s} ${value:>10,.0f}  {close}  {stage}')
