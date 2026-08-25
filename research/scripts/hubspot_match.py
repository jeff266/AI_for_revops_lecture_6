#!/usr/bin/env python3
"""
Fuzzy-match a target list against a HubSpot export and append the Company ID.

The Aug 2026 export was a DEALS export, so the company name lives in
"Associated Company" and the id in "Associated Company IDs". Falls back to a
"Company Name"/"Record ID" pair if given a real Companies export.

Match policy:
  >= AUTO      accept
  MIN..AUTO    report for review, do NOT accept  (this is what caught
                                                  CircleCI~Circle and
                                                  Clari~Clarify.ai)
  < MIN        no match

Usage:
  python3 hubspot_match.py TARGET_CSV HUBSPOT_CSV [-o OUT_CSV]
"""
import argparse, csv, difflib, re, sys

AUTO, MIN = 0.92, 0.82

# Dropped before comparison so "Acme Labs, Inc." == "Acme".
SUFFIX = (r'\b(inc|llc|corp|corporation|ltd|limited|co|company|technologies'
          r'|technology|labs|software|systems|group|holdings|platform)\b')
# Product-style TLDs used as part of the brand: "Apollo.io" -> "apollo".
TLD = r'\.(io|ai|com|dev|app|co|us|so|security|tech)\b'

HS_NAME = ("Associated Company", "Company Name", "Name")
HS_ID   = ("Associated Company IDs", "Record ID", "Company ID")


def norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(TLD, '', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    s = re.sub(SUFFIX, ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def aliases(name: str):
    """'Intercom (Fin)' -> ['Intercom (Fin)', 'Intercom', 'Fin'].

    Target-list names carry renames in parentheses, so a company in the CRM
    under either its old or new name still matches.
    """
    out = [name]
    m = re.match(r'^(.*?)\s*\((?:formerly\s+)?(.*?)\)\s*$', name)
    if m:
        out += [m.group(1), m.group(2)]
    return [a.strip() for a in out if a.strip()]


def pick(fieldnames, candidates, label):
    for c in candidates:
        if c in fieldnames:
            return c
    sys.exit(f"error: no {label} column found. looked for {candidates}, "
             f"file has {fieldnames}")


def load_hubspot(path):
    """Return {normalized_name: (original_name, id)} and any name->many-ids conflicts."""
    rdr = csv.DictReader(open(path))
    ncol = pick(rdr.fieldnames, HS_NAME, "company-name")
    icol = pick(rdr.fieldnames, HS_ID, "company-id")
    seen, conflicts = {}, {}
    for r in rdr:
        n = (r[ncol] or '').strip()
        i = (r[icol] or '').strip()
        if not n:
            continue
        conflicts.setdefault(n, set()).add(i)
        seen.setdefault(norm(n), (n, i))
    return seen, {k: v for k, v in conflicts.items() if len(v) > 1}, ncol, icol


def best_match(company, index):
    """Exact on any alias, else highest ratio across aliases x index."""
    for a in aliases(company):
        k = norm(a)
        if k in index:
            return 'exact', index[k][0], index[k][1], 1.0
    best = (0.0, None)
    for a in aliases(company):
        k = norm(a)
        for cand in index:
            r = difflib.SequenceMatcher(None, k, cand).ratio()
            if r > best[0]:
                best = (r, cand)
    r, cand = best
    if cand is None:
        return None
    if r >= AUTO:
        return 'fuzzy', index[cand][0], index[cand][1], round(r, 3)
    if r >= MIN:
        return 'review', index[cand][0], index[cand][1], round(r, 3)
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('target'); p.add_argument('hubspot')
    p.add_argument('-o', '--out')
    a = p.parse_args()
    out_path = a.out or a.target

    index, conflicts, ncol, icol = load_hubspot(a.hubspot)
    print(f"hubspot: {len(index)} unique companies via {ncol!r}/{icol!r}")
    for n, ids in conflicts.items():
        print(f"  WARN {n!r} maps to {len(ids)} ids: {sorted(ids)} - using first")

    rows = list(csv.DictReader(open(a.target)))
    # Idempotent: drop prior match columns so re-running doesn't duplicate them.
    cols = [c for c in rows[0].keys()
            if c not in ("HubSpot Company ID", "HubSpot Matched Name")]

    tally = {'exact': 0, 'fuzzy': 0, 'review': 0, 'none': 0}
    review = []
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(cols + ["HubSpot Company ID", "HubSpot Matched Name"])
        for r in rows:
            m = best_match(r['Company'], index)
            kind = m[0] if m else 'none'
            tally[kind] += 1
            if kind in ('exact', 'fuzzy'):
                hid, hname = m[2], m[1]
            else:
                hid, hname = '', ''
                if kind == 'review':
                    review.append((r['Company'], m[1], m[3]))
            w.writerow([r[c] for c in cols] + [hid, hname])

    print(f"\nexact {tally['exact']}  fuzzy {tally['fuzzy']}  "
          f"review {tally['review']}  none {tally['none']}  of {len(rows)}")
    if review:
        print(f"\nreview band ({MIN}-{AUTO}) - NOT written, confirm by hand:")
        for c, h, s in review:
            print(f"  {c!r} ~ {h!r} ({s})")
    print(f"\nwrote {out_path}")


if __name__ == '__main__':
    main()
