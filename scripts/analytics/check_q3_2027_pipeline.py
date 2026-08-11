#!/usr/bin/env python3
"""
Check Q3 2027 pipeline to match HubSpot report.
Q3 = Aug 1 - Oct 31, 2027
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Q3 2027 = Aug 1 - Oct 31, 2027
result = sb.table('deals').select('deal_id, company_name, close_date, deal_value, deal_status, stage, pipeline_id').gte('close_date', '2027-08-01').lte('close_date', '2027-10-31').execute()

deals = result.data
print(f"Total deals with Q3 2027 close_date: {len(deals)}")

# Separate by pipeline
sales_deals = [d for d in deals if d.get('pipeline_id') == 'default' and d.get('deal_status') in ['active', 'prospective']]
renewal_deals = [d for d in deals if d.get('pipeline_id') != 'default' and d.get('deal_status') in ['active', 'prospective']]

sales_value = sum(float(d.get('deal_value') or 0) for d in sales_deals)
renewal_value = sum(float(d.get('deal_value') or 0) for d in renewal_deals)

print(f'\nQ3 2027 (Aug 1 - Oct 31) Open Pipeline:')
print(f'')
print(f'Sales (New ARR):     {len(sales_deals):3d} deals  ${sales_value:>12,.2f}')
print(f'Renewal (Exp ARR):   {len(renewal_deals):3d} deals  ${renewal_value:>12,.2f}')
print(f'                     ---           --------------')
print(f'Total:               {len(sales_deals) + len(renewal_deals):3d} deals  ${sales_value + renewal_value:>12,.2f}')
print(f'')
print(f'HubSpot shows: $7,798,832.45')
print(f'Difference: ${(sales_value + renewal_value) - 7798832.45:>12,.2f}')
print(f'')

# Show top 15 deals
all_open = sales_deals + renewal_deals
all_open.sort(key=lambda x: float(x.get('deal_value') or 0), reverse=True)

print(f'Top 15 Q3 2027 deals:')
for i, d in enumerate(all_open[:15], 1):
    company = (d.get('company_name') or 'Unknown')[:35]
    value = float(d.get('deal_value') or 0)
    close = d.get('close_date') or 'N/A'
    stage = (d.get('stage') or 'N/A')[:20]
    pipeline = 'Sales' if d.get('pipeline_id') == 'default' else 'Renewal'
    print(f'{i:2d}. {company:35s} ${value:>10,.0f}  {close}  {stage:20s} [{pipeline}]')
