#!/usr/bin/env python3
"""
Check total open sales pipeline across all close dates.
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all open deals in Sales pipeline
result = sb.table('deals').select('deal_id, company_name, close_date, deal_value, deal_status, stage, pipeline_id').in_('deal_status', ['active', 'prospective']).execute()

deals = result.data

# Filter to Sales pipeline (assuming pipeline_id 'default' or specific ID)
sales_deals = [d for d in deals if d.get('pipeline_id') == 'default']
renewal_deals = [d for d in deals if d.get('pipeline_id') != 'default']

sales_value = sum(float(d.get('deal_value') or 0) for d in sales_deals)
renewal_value = sum(float(d.get('deal_value') or 0) for d in renewal_deals)

print(f'Total Open Pipeline by Pipeline:')
print(f'')
print(f'Sales (default):   {len(sales_deals):3d} deals  ${sales_value:>12,.0f}')
print(f'Renewal:           {len(renewal_deals):3d} deals  ${renewal_value:>12,.0f}')
print(f'                   ---           --------------')
print(f'Total:             {len(deals):3d} deals  ${sales_value + renewal_value:>12,.0f}')
print(f'')

# Break down Sales by close_date quarter (fiscal year starting Feb 1)
q2_sales = [d for d in sales_deals if d.get('close_date') and '2026-05-01' <= d.get('close_date') <= '2026-07-31']
q3_sales = [d for d in sales_deals if d.get('close_date') and '2026-08-01' <= d.get('close_date') <= '2026-10-31']
q4_sales = [d for d in sales_deals if d.get('close_date') and '2026-11-01' <= d.get('close_date') <= '2027-01-31']
future_sales = [d for d in sales_deals if d.get('close_date') and d.get('close_date') > '2027-01-31']
no_date_sales = [d for d in sales_deals if not d.get('close_date')]

q2_value = sum(float(d.get('deal_value') or 0) for d in q2_sales)
q3_value = sum(float(d.get('deal_value') or 0) for d in q3_sales)
q4_value = sum(float(d.get('deal_value') or 0) for d in q4_sales)
future_value = sum(float(d.get('deal_value') or 0) for d in future_sales)
no_date_value = sum(float(d.get('deal_value') or 0) for d in no_date_sales)

print(f'Sales Pipeline by Close Quarter:')
print(f'  Q2 (May-Jul):      {len(q2_sales):3d} deals  ${q2_value:>12,.0f}')
print(f'  Q3 (Aug-Oct):      {len(q3_sales):3d} deals  ${q3_value:>12,.0f}')
print(f'  Q4 (Nov-Jan):      {len(q4_sales):3d} deals  ${q4_value:>12,.0f}')
print(f'  Future (Feb+):     {len(future_sales):3d} deals  ${future_value:>12,.0f}')
print(f'  No close_date:     {len(no_date_sales):3d} deals  ${no_date_value:>12,.0f}')
print(f'')

# Show top 10 Q3 Sales deals
if q3_sales:
    print(f'Top 10 Q3 (Aug-Oct) Sales deals:')
    q3_sales.sort(key=lambda x: float(x.get('deal_value') or 0), reverse=True)
    for d in q3_sales[:10]:
        company = (d.get('company_name') or 'Unknown')[:35]
        value = float(d.get('deal_value') or 0)
        close = d.get('close_date') or 'N/A'
        stage = (d.get('stage') or 'N/A')[:20]
        print(f'  {company:35s} ${value:>10,.0f}  {close}  {stage}')
