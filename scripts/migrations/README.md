# Database Migrations

All schema changes live here as numbered SQL files. Run them with `setup_supabase.py` — it tracks which migrations have already been applied and only runs new ones.

## Initial setup

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-role-key"

python scripts/setup_supabase.py
```

## Adding a new migration

Create the next numbered file, e.g. `003_add_feature_flags.sql`, commit it to the repo, and run `setup_supabase.py` again on any deployment that needs updating. Already-applied migrations are skipped automatically.

## Migration files

| File | Description |
|---|---|
| `001_initial_schema.sql` | Core tables: deals, analyses, calls, objections, rep_performance |
| `002_add_deal_history.sql` | Add deal_status, create_date, days_to_close for closed deal tracking |
| `003_add_component_scores.sql` | Add methodology-agnostic `component_scores` JSONB (+ GIN index) to analyses |

## Getting your Supabase credentials

1. Supabase dashboard → your project → Settings → API
2. **Project URL** → `SUPABASE_URL`
3. **service_role** key (not anon) → `SUPABASE_SERVICE_KEY`

Add both as GitHub Secrets under repo → Settings → Environments → Agent.
