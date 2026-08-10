#!/usr/bin/env python3
"""
Supabase setup script with migration tracking.

Runs all pending migrations in order, then VERIFIES each one actually
took effect (via a live PostgREST query, not just "the API call didn't
raise") before recording it as applied. Already-verified migrations
are skipped — safe to run repeatedly.

Why verification, not just execution: supabase-py's REST client has
no generic raw-SQL execution endpoint. This script's only way to run
raw DDL is client.rpc('exec_sql', ...), which requires a custom
'exec_sql' Postgres function that most Supabase projects do NOT have
by default. When that RPC is missing, calling it raises — and a
previous version of this script swallowed that exception silently,
then recorded the migration as applied anyway. The tables never got
created; the tracking table said otherwise (production bug: 005/006
never existed despite showing "✓ Done"). This version never trusts
"the call didn't raise" — it always confirms the specific table or
column a migration claims to add is genuinely queryable before
marking it done.

Usage:
    export SUPABASE_URL="https://your-project.supabase.co"
    export SUPABASE_SERVICE_KEY="your-service-role-key"
    python scripts/setup_supabase.py
"""
import os
import re
import sys
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


MIGRATIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS _migrations (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);"""


def _table_exists(client, table_name: str) -> bool:
    """
    The only raw-SQL-free way to know a table is genuinely queryable:
    ask PostgREST for it directly and see whether it complains. This
    works on every Supabase project out of the box — unlike raw SQL
    execution or information_schema access, neither of which is
    reachable through the standard REST client without a custom RPC
    function most projects don't have.
    """
    try:
        client.table(table_name).select('*', count='exact').limit(0).execute()
        return True
    except Exception:
        return False


def _column_exists(client, table_name: str, column_name: str) -> bool:
    """Same idea as _table_exists, scoped to one column."""
    try:
        client.table(table_name).select(column_name).limit(0).execute()
        return True
    except Exception:
        return False


def ensure_migrations_table(client) -> bool:
    """
    Create the _migrations tracking table if it doesn't exist, and
    VERIFY it actually exists afterward. This isn't a numbered
    migration file, but it's subject to the exact same "exec_sql may
    not exist" failure mode, so it gets the same execute-then-verify
    treatment. Returns True if _migrations is confirmed queryable.
    """
    if _table_exists(client, '_migrations'):
        return True

    try:
        client.rpc('exec_sql', {'sql': MIGRATIONS_TABLE_SQL}).execute()
    except Exception:
        pass  # Checked below regardless of whether this raised.

    if _table_exists(client, '_migrations'):
        return True

    print('❌ Could not create the _migrations tracking table, and this')
    print('   client has no working exec_sql RPC to run raw DDL with.')
    print('   Paste this into the Supabase dashboard → SQL Editor, run')
    print('   it once, then re-run this script:')
    print()
    print(MIGRATIONS_TABLE_SQL)
    print()
    return False


def get_applied(client) -> set:
    """Return set of already-applied migration names."""
    try:
        result = client.table('_migrations').select('name').execute()
        return {r['name'] for r in (result.data or [])}
    except Exception:
        # Table doesn't exist yet — no migrations applied
        return set()


def _first_ddl_fingerprint(sql: str):
    """
    Parse the first CREATE TABLE or ALTER TABLE ... ADD COLUMN
    statement in a migration into a verifiable fingerprint:
      ('table', table_name)               for CREATE TABLE
      ('column', table_name, column_name) for ALTER TABLE ... ADD COLUMN
    Returns None if the SQL has neither (nothing to verify against —
    e.g. an index-only migration). Derived by parsing the SQL text
    itself, not a hardcoded per-migration list, so it never rots as
    new migrations are added.
    """
    create_match = re.search(
        r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?"?(\w+)"?',
        sql, re.IGNORECASE)
    alter_match = re.search(
        r'ALTER TABLE\s+"?(\w+)"?\s+ADD COLUMN\s+(?:IF NOT EXISTS\s+)?"?(\w+)"?',
        sql, re.IGNORECASE)

    candidates = []
    if create_match:
        candidates.append((create_match.start(), ('table', create_match.group(1))))
    if alter_match:
        candidates.append((alter_match.start(),
                           ('column', alter_match.group(1), alter_match.group(2))))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def _verify_fingerprint(client, fingerprint) -> bool:
    """
    Check whether the fingerprinted table/column is genuinely
    queryable — the only trustworthy signal that a migration's DDL
    actually took effect.
    """
    if fingerprint is None:
        return True
    if fingerprint[0] == 'table':
        return _table_exists(client, fingerprint[1])
    _, table_name, column_name = fingerprint
    return _column_exists(client, table_name, column_name)


def execute_sql(client, sql: str) -> bool:
    """
    Execute one SQL statement via the exec_sql RPC. Returns whether
    the call itself succeeded — NOT whether the DDL took effect (see
    _verify_fingerprint for that). Most Supabase projects don't have a
    custom exec_sql function, so this returning False is the common
    case, not something to hide.
    """
    try:
        client.rpc('exec_sql', {'sql': sql}).execute()
        return True
    except Exception:
        return False


def run_migration(client, path: Path) -> str:
    """
    Run a single migration file, then verify it actually took effect
    before recording it as applied.

    Returns one of:
      'applied'    — DDL confirmed present, recorded in _migrations.
      'unverified' — no working exec_sql RPC on this client; full SQL
                     printed for manual application, NOT recorded.
      'failed'     — exec_sql ran without raising, but the target
                     table/column still isn't queryable; printed for
                     investigation, NOT recorded.
    """
    sql = path.read_text()
    statements = [s.strip() for s in sql.split(';') if s.strip()]

    any_executed = False
    for stmt in statements:
        if execute_sql(client, stmt):
            any_executed = True

    fingerprint = _first_ddl_fingerprint(sql)
    verified = _verify_fingerprint(client, fingerprint)

    if verified:
        client.table('_migrations').insert({
            'name': path.name,
            'applied_at': datetime.now(timezone.utc).isoformat(),
        }).execute()
        return 'applied'

    if not any_executed:
        print('    ⚠️  This client has no working exec_sql RPC — raw DDL')
        print('    could not be executed. Paste this into the Supabase')
        print('    dashboard → SQL Editor, run it once, then re-run this')
        print('    script to verify and record it:')
        print()
        print(sql.strip())
        print()
        return 'unverified'

    # exec_sql ran without raising, but the target still isn't there —
    # find and print the exact statement responsible.
    target = (f"table '{fingerprint[1]}'" if fingerprint[0] == 'table'
              else f"column '{fingerprint[2]}' on table '{fingerprint[1]}'")
    print(f'    ❌ Ran without error, but {target} still is not queryable.')
    print('    The statement that should have created it:')
    print()
    for stmt in statements:
        if _first_ddl_fingerprint(stmt + ';') == fingerprint:
            print(f'      {stmt};')
            break
    print()
    return 'failed'


def attempt_schema_reload(client):
    """
    PostgREST caches the schema; new tables/columns aren't queryable
    through the REST API until it reloads. Try the built-in notify
    channel; if that's not reachable (same raw-SQL limitation as
    migrations), print the manual fallback checklist rather than
    leaving the cache silently stale.
    """
    try:
        client.rpc('exec_sql', {
            'sql': "SELECT pg_notify('pgrst', 'reload schema');"
        }).execute()
        print('✓ PostgREST schema reload notified')
        return
    except Exception:
        pass

    print()
    print('⚠️  Could not trigger a PostgREST schema reload automatically.')
    print('   Newly-verified tables/columns may not be visible through')
    print('   the REST API until the cache reloads. If writes to them')
    print('   fail with "column/table not found" despite verifying above:')
    print('     1. Supabase dashboard → SQL Editor → run:')
    print("          SELECT pg_notify('pgrst', 'reload schema');")
    print('     2. Confirm visibility with a direct REST call, e.g.:')
    print('          curl "$SUPABASE_URL/rest/v1/<table>?limit=1" \\')
    print('               -H "apikey: $SUPABASE_SERVICE_KEY" \\')
    print('               -H "Authorization: Bearer $SUPABASE_SERVICE_KEY"')
    print('        (a schema/"does not exist" error means the cache')
    print('         still hasn\'t picked up the change)')
    print('     3. Still stale: Supabase dashboard → Settings → General')
    print('        → Restart project (last resort, brief downtime).')


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

    if not ensure_migrations_table(client):
        sys.exit(1)

    applied = get_applied(client)

    migrations_dir = Path('scripts/migrations')
    if not migrations_dir.exists():
        print(f'ERROR: {migrations_dir} not found.')
        print('Run from the repo root directory.')
        sys.exit(1)

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
        any_applied = False
        any_unresolved = False
        for path in pending:
            print(f'  → {path.name}')
            outcome = run_migration(client, path)
            if outcome == 'applied':
                print('    ✓ Done (verified)')
                any_applied = True
            else:
                any_unresolved = True
        print()

        if any_applied:
            attempt_schema_reload(client)
            print()

        if any_unresolved:
            print('❌ One or more migrations could not be verified — see')
            print('   above. Re-run this script after resolving them.')
            sys.exit(1)

    print('Verifying tables:')
    verify_tables(client)
    print('\nSetup complete.')


if __name__ == '__main__':
    main()
