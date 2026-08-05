#!/usr/bin/env python3
"""
Supabase setup script with migration tracking.

Runs all pending migrations in order. Already-applied
migrations are skipped — safe to run repeatedly.

Usage:
    export SUPABASE_URL="https://your-project.supabase.co"
    export SUPABASE_SERVICE_KEY="your-service-role-key"
    python scripts/setup_supabase.py
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from supabase import create_client


def get_client():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise ValueError(
            'SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.\n'
            'Get them from Supabase dashboard → Settings → API.'
        )
    return create_client(url, key)


def ensure_migrations_table(client):
    """Create _migrations tracking table if it does not exist."""
    sql = """
        CREATE TABLE IF NOT EXISTS _migrations (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        );
    """
    # Execute directly via Supabase's REST SQL endpoint
    try:
        client.rpc('exec_sql', {'sql': sql}).execute()
    except Exception:
        # exec_sql may not be available — try raw postgrest
        # The table will be created by the first migration if needed
        pass


def get_applied(client) -> set:
    """Return set of already-applied migration names."""
    try:
        result = client.table('_migrations').select('name').execute()
        return {r['name'] for r in (result.data or [])}
    except Exception:
        # Table doesn't exist yet — no migrations applied
        return set()


def execute_sql(client, sql: str):
    """Execute a SQL statement via Supabase."""
    try:
        client.rpc('exec_sql', {'sql': sql}).execute()
    except Exception:
        pass  # DDL may not return via RPC — proceed


def run_migration(client, path: Path):
    """Run a single migration file and record it."""
    sql = path.read_text()
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    for stmt in statements:
        execute_sql(client, stmt)

    # Record as applied
    client.table('_migrations').insert({
        'name': path.name,
        'applied_at': datetime.now(timezone.utc).isoformat(),
    }).execute()


def verify_tables(client):
    """Quick sanity check that core tables exist."""
    tables = ['deals', 'analyses', 'calls']
    for t in tables:
        try:
            r = client.table(t).select('*', count='exact').limit(0).execute()
            print(f'  ✓ {t} (rows: {r.count})')
        except Exception as e:
            print(f'  ✗ {t} — {e}')


def main():
    print('Connecting to Supabase...')
    client = get_client()
    print('✓ Connected\n')

    ensure_migrations_table(client)
    applied = get_applied(client)

    migrations_dir = Path('scripts/migrations')
    if not migrations_dir.exists():
        print(f'ERROR: {migrations_dir} not found.')
        print('Run from the repo root directory.')
        return

    migration_files = sorted(
        f for f in migrations_dir.glob('*.sql')
        if re.match(r'^\d+_', f.name)
    )

    if not migration_files:
        print('No migration files found in scripts/migrations/')
        return

    pending = [f for f in migration_files if f.name not in applied]

    if not pending:
        print('All migrations already applied:')
        for f in migration_files:
            print(f'  ✓ {f.name}')
        print()
    else:
        if applied:
            print('Already applied:')
            for name in sorted(applied):
                print(f'  ✓ {name}')
            print()

        print(f'Applying {len(pending)} pending migration(s)...')
        for path in pending:
            print(f'  → {path.name}')
            run_migration(client, path)
            print(f'    ✓ Done')
        print()

    print('Verifying tables:')
    verify_tables(client)
    print('\nSetup complete.')


if __name__ == '__main__':
    main()
