#!/usr/bin/env python3
"""
Seed user_personas from config/client.yaml (team roster + admins).

WHY (FIX_DYNAMIC_FALLBACK_PATTERN, PART 4):
Every Slack request logs `[PERSONA] Unknown user ... treating as 'other'` —
nobody is mapped, so every answer runs un-personalised, and name-based
handlers can't resolve the asker. This seeds the team from config so:
  * rows exist keyed by email (name, role, role_group) — this alone makes
    api/handlers._resolve_owner_email resolve a rep's name to their email;
  * the two Slack IDs we actually know (the admins) are bound directly, so
    those users are recognised immediately.

Slack IDs we do NOT know are left NULL. They bind lazily on the user's first
message IF the message carries their email — see the report in the task for
the one remaining gap (the Zapier payload / get_user_persona call currently
passes no email, so lazy binding never fires; that is a separate data/plumbing
fix, called out explicitly rather than guessed here).

Run:
  python scripts/seed_personas_from_config.py            # dry run (prints)
  python scripts/seed_personas_from_config.py --write    # upsert to Supabase
"""
import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# Free-text roster roles → normalised role key.
ROLE_ALIASES = {
    "sdr": "sdr", "bdr": "sdr",
    "sales development representative": "sdr",
    "account executive": "ae", "ae": "ae",
    "account manager": "am", "am": "am",
    "vp revenue operations": "vp_revops",
    "vp of revenue operations": "vp_revops",
    "revops": "revops",
    "cro": "cro", "chief revenue officer": "cro",
    "ceo": "ceo", "cto": "cto",
    "vp sales": "vp_sales", "sdl": "sdl",
}

# role key → persona group for voice routing.
ROLE_TO_GROUP = {
    "ceo": "executive", "cto": "executive", "cro": "executive",
    "vp_sales": "sales_leadership", "sdl": "sales_leadership",
    "vp_revops": "operational", "revops": "operational",
    "ae": "ic", "am": "ic", "sdr": "ic",
    "other": "other",
}


def _norm_role(raw: str) -> str:
    key = (raw or "").strip().lower()
    # config_overrides already uses canonical role keys (e.g. "vp_revops");
    # pass those through. The roster uses free text ("VP Revenue Operations").
    if key in ROLE_TO_GROUP:
        return key
    return ROLE_ALIASES.get(key, "other")


def _is_placeholder(slack_id: str) -> bool:
    if not slack_id:
        return True
    s = slack_id.strip()
    return s.startswith("U_") or "PLACEHOLDER" in s.upper()


def build_personas(config: dict) -> list[dict]:
    by_email: dict[str, dict] = {}

    # 1. Team roster.
    for m in config.get("team", {}).get("members", []) or []:
        email = (m.get("email") or "").strip().lower()
        if not email:
            continue
        role = _norm_role(m.get("role"))
        slack_id = m.get("slack_user_id")
        by_email[email] = {
            "email": email,
            "name": m.get("name"),
            "display_name": m.get("name"),
            "role": role,
            "role_group": ROLE_TO_GROUP.get(role, "other"),
            "title": m.get("title"),
            "slack_user_id": None if _is_placeholder(slack_id) else slack_id,
            "source": "config_seed",
        }

    # 2. Role authority from config_overrides (wins over roster inference).
    for email, ov in (config.get("config_overrides") or {}).items():
        email = email.strip().lower()
        role = _norm_role(ov.get("role"))
        row = by_email.setdefault(email, {
            "email": email, "name": None, "display_name": None,
            "slack_user_id": None, "source": "config_seed",
        })
        row["role"] = role
        row["role_group"] = ROLE_TO_GROUP.get(role, "other")
        if ov.get("title"):
            row["title"] = ov["title"]

    return list(by_email.values())


# Columns we upsert. slack_user_id / name / display_name / title use COALESCE
# on conflict so a re-run never wipes a value that's already there (e.g. a
# Slack ID a user self-bound, or a name we don't have in config).
_COLS = ["email", "name", "display_name", "role", "role_group",
         "persona", "title", "slack_user_id", "source"]
_COALESCE = {"name", "display_name", "title", "slack_user_id"}


def _sql_lit(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def emit_sql(personas: list[dict]) -> str:
    rows = []
    for p in sorted(personas, key=lambda x: x["email"]):
        vals = []
        for c in _COLS:
            v = p.get(c)
            if c == "persona" and v is None:
                v = p.get("role_group")  # persona mirrors role_group
            vals.append(_sql_lit(v))
        rows.append("  (" + ", ".join(vals) + ")")
    set_clause = ",\n".join(
        (f"  {c} = COALESCE(EXCLUDED.{c}, user_personas.{c})"
         if c in _COALESCE else f"  {c} = EXCLUDED.{c}")
        for c in _COLS if c != "email")
    return (
        "INSERT INTO user_personas\n"
        f"  ({', '.join(_COLS)})\nVALUES\n"
        + ",\n".join(rows)
        + "\nON CONFLICT (email) DO UPDATE SET\n"
        + set_clause
        + ",\n  updated_at = now();"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Upsert to Supabase (default: dry run / print only)")
    ap.add_argument("--sql", action="store_true",
                    help="Print an idempotent INSERT ... ON CONFLICT and exit")
    args = ap.parse_args()

    config = yaml.safe_load(open(REPO / "config" / "client.yaml"))
    personas = build_personas(config)
    # persona mirrors role_group (its original voice-routing meaning).
    for p in personas:
        p.setdefault("persona", p.get("role_group"))

    if args.sql:
        print(emit_sql(personas))
        return

    print(f"\n{'WRITE' if args.write else 'DRY RUN'} — "
          f"{len(personas)} personas from config/client.yaml\n")
    print(f"  {'email':38} {'name':20} {'role':12} {'group':16} slack_user_id")
    print("  " + "-" * 96)
    bound = 0
    for p in sorted(personas, key=lambda x: x["email"]):
        sid = p.get("slack_user_id")
        if sid:
            bound += 1
        print(f"  {p['email']:38} {str(p.get('name')):20} "
              f"{str(p.get('role')):12} {str(p.get('role_group')):16} "
              f"{sid or '(lazy — binds on first message by email)'}")
    print(f"\n  {bound} of {len(personas)} have a known Slack ID; "
          f"the rest bind lazily by email.")

    if not args.write:
        print("\n(dry run — pass --write to upsert)")
        return

    from supabase_client import SupabaseWriter
    sb = SupabaseWriter().client
    ok = 0
    for p in personas:
        # Drop None-valued keys so an upsert never overwrites an existing
        # slack_user_id / name / title with NULL (a user may already have
        # self-bound). email/role/role_group are always present.
        row = {k: v for k, v in p.items() if v is not None}
        try:
            sb.table("user_personas").upsert(
                row, on_conflict="email").execute()
            ok += 1
        except Exception as e:
            print(f"  ✗ {p['email']}: {e}")
    print(f"\n✓ upserted {ok}/{len(personas)} personas")


if __name__ == "__main__":
    main()
