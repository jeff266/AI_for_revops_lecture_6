"""Typed query tools for dynamic CRO agent queries."""
import sys, json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from supabase_client import select_all

_VALID_COLUMNS = {}

def _init_valid_columns(sb):
    global _VALID_COLUMNS
    if _VALID_COLUMNS:
        return
    rows = select_all(sb, "data_dictionary", columns="supabase_table,supabase_column",
        filters=[("eq", "is_queryable", True)])
    for r in rows:
        _VALID_COLUMNS.setdefault(r["supabase_table"], set()).add(r["supabase_column"])

def _validate_columns(table, columns):
    valid = _VALID_COLUMNS.get(table, set())
    good, bad = [], []
    for c in columns:
        (good if c in valid or not valid else bad).append(c)
    if bad:
        print(f"  ⚠️  Ignoring unknown columns for {table}: {bad}")
    return good or list(valid)[:10]

def _validate_filters(table, filters):
    valid = _VALID_COLUMNS.get(table, set())
    return [(op, col, val) for op, col, val in filters if col in valid or not valid]

VALID_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is_", "in_"}

async def filter_table(sb, table, columns=None, filters=None, limit=50, order_by=None):
    _init_valid_columns(sb)
    # Analyses table has large JSONB - limit to 50 rows max
    max_limit = 50 if table == "analyses" else 200
    limit = min(limit or 50, max_limit)
    cols = _validate_columns(table, columns or [])
    # If column validation found nothing valid, use safe defaults
    if not cols:
        cols = ["deal_id", "company_name", "deal_value",
                "deal_status", "close_date"]
    valid_filters = _validate_filters(table, [tuple(f) for f in (filters or [])])
    invalid_ops = [(op,col,val) for op,col,val in valid_filters if op not in VALID_OPS]
    if invalid_ops:
        return {"error": f"Invalid operators: {invalid_ops}. Use one of: {sorted(VALID_OPS)}"}

    # Before building filters, handle None values
    processed_filters = []
    for f in valid_filters:
        op, col, val = f[0], f[1], f[2] if len(f) > 2 else None
        if val is None:
            if op in ("eq", "is_"):
                processed_filters.append(("is_", col, "null"))
            elif op in ("neq", "not_is_", "not.is_"):
                # Mark for special handling — supabase-py
                # needs .not_.is_() not a chained attr
                processed_filters.append(
                    ("__not_null__", col, None))
        else:
            processed_filters.append((op, col, val))

    # Use PostgREST order() for efficient top-N queries
    if order_by:
        col, *dir_ = order_by.split()
        direction = 'desc' if 'desc' in (dir_[0].lower() if dir_ else '') else 'asc'

        # Build query with order before limit for efficiency
        q = sb.table(table).select(",".join(cols) if cols else "*")
        for f in processed_filters:
            q = getattr(q, f[0])(*f[1:])
        q = q.order(col, desc=(direction == 'desc'))
        rows = q.limit(limit).execute().data or []
        return {"rows": rows, "total_found": len(rows), "table": table, "truncated": False}
    else:
        # No ordering - use paginated select_all
        rows = select_all(sb, table, columns=",".join(cols) if cols else "*", filters=processed_filters)
        return {"rows": rows[:limit], "total_found": len(rows), "table": table, "truncated": len(rows) > limit}

async def join_tables(sb, primary_table, primary_key, joined_table, foreign_key,
                      primary_filters=None, joined_columns=None, limit=50):
    _init_valid_columns(sb)
    primary_rows = (await filter_table(sb, primary_table, filters=primary_filters, limit=limit))["rows"]
    if not primary_rows:
        return {"rows": [], "total_found": 0}
    key_values = [r[primary_key] for r in primary_rows if r.get(primary_key)]
    if not key_values:
        return {"rows": primary_rows, "total_found": len(primary_rows)}
    joined = select_all(sb, joined_table,
        columns=",".join(_validate_columns(joined_table, joined_columns or [])) or "*",
        filters=[("in_", foreign_key, key_values)])
    joined_map = {}
    for j in joined:
        joined_map.setdefault(j.get(foreign_key), []).append(j)
    for row in primary_rows:
        row[f"_{joined_table}"] = joined_map.get(row.get(primary_key), [])
    return {"rows": primary_rows, "total_found": len(primary_rows)}

async def aggregate_results(data, group_by, aggregations):
    # Validate and convert aggregations format
    if isinstance(aggregations, list):
        # Convert common list format to dict
        converted = {}
        for item in aggregations:
            if isinstance(item, dict):
                col = item.get("column") or item.get("col", "")
                agg = item.get("agg") or item.get("aggregation", "count")
                if col:
                    converted[col] = agg
        aggregations = converted
    if not isinstance(aggregations, dict) or not aggregations:
        return {"error": "aggregations must be a non-empty dict like {'column': 'sum'}"}

    groups = defaultdict(list)
    for row in data:
        groups[row.get(group_by, "unknown")].append(row)
    result = []
    for key, rows in groups.items():
        entry = {group_by: key}
        for col, agg in aggregations.items():
            vals = [r.get(col) for r in rows if r.get(col) is not None]
            if agg == "sum":
                entry[f"{col}_sum"] = sum(vals)
            elif agg == "count":
                entry[f"{col}_count"] = len(rows)
            elif agg == "avg":
                entry[f"{col}_avg"] = sum(vals)/len(vals) if vals else 0
            elif agg == "max":
                entry[f"{col}_max"] = max(vals) if vals else None
            elif agg == "min":
                entry[f"{col}_min"] = min(vals) if vals else None
        result.append(entry)
    result.sort(key=lambda x: x.get(f"{list(aggregations.keys())[0]}_sum",
        x.get(f"{list(aggregations.keys())[0]}_count", 0)) or 0, reverse=True)
    return {"rows": result, "group_count": len(result),
            "grouped": result}  # keep "grouped" for backward compat

async def compare_periods(sb, table, column, agg, period_a, period_b, date_column="create_date"):
    async def get_val(period):
        rows = (await filter_table(sb, table, columns=[column],
            filters=[("gte", date_column, period["start"]), ("lte", date_column, period["end"])],
            limit=200))["rows"]
        vals = [r.get(column) for r in rows if r.get(column) is not None]
        if agg == "sum": return sum(vals)
        if agg == "count": return len(rows)
        if agg == "avg": return sum(vals)/len(vals) if vals else 0
        return None
    val_a, val_b = await get_val(period_a), await get_val(period_b)
    delta = (val_a - val_b) if (val_a is not None and val_b is not None) else None
    pct = (delta / val_b * 100) if (val_b and delta is not None) else None
    return {"period_a": {**period_a, "value": val_a}, "period_b": {**period_b, "value": val_b},
        "delta": delta, "pct_change": round(pct, 1) if pct else None,
        "trend": ("up" if delta > 0 else "down" if delta < 0 else "flat") if delta is not None else "unknown"}
