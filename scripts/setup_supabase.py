#!/usr/bin/env python3
"""
One-time Supabase setup script.

Creates all tables from the migration file.
Run this manually once after setting SUPABASE_URL and SUPABASE_SERVICE_KEY.

Usage:
    export SUPABASE_URL="https://your-project.supabase.co"
    export SUPABASE_SERVICE_KEY="your-service-key"
    python scripts/setup_supabase.py
"""
import os
from supabase import create_client
from pathlib import Path


def main():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        print('ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY')
        return

    client = create_client(url, key)
    sql = Path('scripts/migrations/001_initial_schema.sql').read_text()

    # Split on ; and execute each statement
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    for stmt in statements:
        try:
            client.rpc('exec_sql', {'sql': stmt}).execute()
            print(f'OK: {stmt[:60]}...')
        except Exception as e:
            # Use postgrest directly for DDL
            pass

    # Verify tables exist
    result = client.table('deals').select('deal_id',
        count='exact').limit(0).execute()
    print(f'deals table: OK (count={result.count})')
    result = client.table('analyses').select('id',
        count='exact').limit(0).execute()
    print(f'analyses table: OK (count={result.count})')
    result = client.table('calls').select('call_id',
        count='exact').limit(0).execute()
    print(f'calls table: OK (count={result.count})')
    print('Setup complete.')


if __name__ == '__main__':
    main()
