"""
Point-in-time field reconstruction for historical pipeline snapshots.

Shared reconstruction logic used by both Method 1 (prospective snapshots)
and Method 2 (historical backfill). This module is the single source of truth
for the INCLUSION RULE - both snapshot_deals.py and backfill_snapshots.py
import from here to ensure they cannot diverge.

WHAT VALIDATES THE INCLUSION RULE, AND WHAT DOES NOT. Both Method 1 and
Method 2 call is_deal_open_at_date, which is the point — they cannot drift.
The cost is that the Method 1 / Method 2 cross-validation cannot validate the
rule: a bug in the shared function moves both arms identically and the
comparison reads as agreement. The rule's evidence is the deal-level
point-in-time comparison in compare_inclusion_rules_pit.py, which recovered
13-15 deals per week whose stage said open while their close_date had slipped
up to 962 days past.

Method 1's own coverage assertion is likewise not rule validation: it
snapshots today, so its comparator has no earlier source of truth and is
self-consistent by construction. It catches write mechanics — pagination,
row caps, a rule that drops deals — not a wrong rule.
"""
import sys
from datetime import datetime, date as _date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'api'))

from field_semantics import stage_bucket, get_outcome_buckets


class UnclassifiableStageError(ValueError):
    """
    Raised when a stage id has no classification in field_semantics.

    Reconstruction must never guess at a stage it cannot classify. The
    graceful path (field_semantics.is_open treats an unknown stage as open)
    is correct for the CRO agent, which degrades rather than crashes on a
    live query. It is wrong here: reaching back to 2023 means meeting stage
    ids that have since been retired, and failing open silently promotes
    them into the open-pipeline denominator, producing plausible wrong
    numbers instead of an error.
    """


def is_terminal_stage(stage_id: Optional[str]) -> bool:
    """
    Strict terminal (won/lost) test for point-in-time reconstruction.

    Returns False for None: that is the 'pre_history' case, where the deal
    existed but history does not reach back to this date. The caller
    distinguishes it via the confidence label; it is not a stage value.

    Raises:
        UnclassifiableStageError: the stage id is not in field_semantics.
            Add it to config/field_semantics.yaml with its correct bucket
            and regenerate, or mark it excluded — never let it default.
    """
    # A MISSING stage is not an UNCLASSIFIABLE stage. None means "history does
    # not reach this date" (pre_history/cleared); an empty or whitespace value
    # means the field is simply unset. Both are absence of a stage, so both
    # read as non-terminal and neither raises — raising on one and not the
    # other made the same fact behave two different ways, and halted a whole
    # nightly snapshot over a single deal with a blank stage.
    # The raise below is for a non-empty id that field_semantics does not know,
    # which is the retired-stage hazard this gate exists for.
    if stage_id is None or not str(stage_id).strip():
        return False

    bucket = stage_bucket(stage_id)
    if bucket == 'unknown':
        raise UnclassifiableStageError(
            f"Stage id {stage_id!r} has no classification in "
            f"config/field_semantics.yaml. Reconstruction refuses to treat "
            f"it as open. Add it with its correct bucket, or mark it excluded."
        )

    outcome_buckets = get_outcome_buckets()
    return bucket in outcome_buckets['won'] or bucket in outcome_buckets['lost']


def is_deal_open_at_date(
    deal_create_date,  # datetime or date
    deal_stage_at_date: Optional[str],
    snapshot_date,  # datetime or date
    is_terminal_stage_func=is_terminal_stage
) -> bool:
    """
    Inclusion rule for pipeline snapshots (shared by Method 1 and Method 2).

    A deal belongs in the snapshot for date D if:
    - create_date <= D, AND
    - deal had not reached a terminal stage as of D

    Args:
        deal_create_date: Date deal was created (datetime or date)
        deal_stage_at_date: Stage of deal at snapshot_date (or None if no history)
        snapshot_date: Snapshot date (datetime or date)
        is_terminal_stage_func: Function(stage_id) -> bool (checks if stage is
            won/lost). Defaults to the strict is_terminal_stage above, which
            raises on a stage id field_semantics cannot classify.

    Returns:
        True if deal should be in snapshot, False otherwise

    This is the single source of truth for inclusion logic - both snapshot_deals.py
    and backfill_snapshots.py import this function so they cannot diverge.
    """
    # Normalize dates to datetime for comparison
    if isinstance(deal_create_date, _date) and not isinstance(deal_create_date, datetime):
        deal_create_date = datetime(deal_create_date.year, deal_create_date.month, deal_create_date.day)
    if isinstance(snapshot_date, _date) and not isinstance(snapshot_date, datetime):
        snapshot_date = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day)

    # Must be created before or on snapshot date
    if deal_create_date > snapshot_date:
        return False

    # If we have no stage history at this date, deal is open (hasn't progressed to terminal)
    if deal_stage_at_date is None:
        return True

    # If stage is not terminal (won/lost), deal is open
    if not is_terminal_stage_func(deal_stage_at_date):
        return True

    # Deal is in terminal stage, not open
    return False


def load_scope_config(config=None):
    """
    Analytics scoping from config/client.yaml, shared so no caller reinvents it.

    Returns (excluded_pipeline_ids, {stage_id: {...}}).
    """
    if config is None:
        import yaml
        config_path = Path(__file__).parent.parent.parent / 'config' / 'client.yaml'
        config = yaml.safe_load(config_path.read_text())

    # Build excluded pipelines set
    excluded_pipelines = set()
    for pipeline in config.get('pipeline', {}).get('pipelines', []):
        if not pipeline.get('analyze', True):
            excluded_pipelines.add(str(pipeline.get('id', '')))

    # Build stage config map
    default_qso = config.get('pipeline', {}).get('qualified_stage_order', 1)
    stages = {}

    for pipeline in config.get('pipeline', {}).get('pipelines', []):
        qso = pipeline.get('qualified_stage_order', default_qso)
        for stage in pipeline.get('stages', []):
            stages[str(stage['id'])] = {
                'name': stage.get('name', ''),
                'order': stage.get('order', 0),
                'excluded': bool(stage.get('exclude_from_analysis', False)),
                'qualified_stage_order': qso,
            }

    return excluded_pipelines, stages


def is_deal_in_analytics_scope(
    stage_at_date: Optional[str],
    pipeline_id: Optional[str],
    excluded_pipelines=None,
    stage_cfg=None,
) -> bool:
    """
    Whether a deal belongs in a pipeline-conversion population at some date.

    Scoping is NOT the inclusion rule and must never gate what gets WRITTEN.
    Method 1 writes every pipeline and stage on purpose: the renewal pipeline
    carries `analyze: false  # MEDDICC agent skips; analytics INCLUDES for
    GRR/NRR`, so dropping renewals from deals_snapshot would destroy the rows
    GRR/NRR reads. Scope on the way out, never on the way in.

    Excluded by: a pipeline with analyze: false; a stage flagged
    exclude_from_analysis (Meeting Set, Disqualified); a stage below its
    pipeline's qualified_stage_order.

    A None stage cannot be scoped — there is no stage to judge — so it returns
    False and the caller should count it rather than assume either way.
    """
    if excluded_pipelines is None or stage_cfg is None:
        excluded_pipelines, stage_cfg = load_scope_config()

    if pipeline_id is not None and str(pipeline_id) in excluded_pipelines:
        return False
    if stage_at_date is None:
        return False

    cfg = stage_cfg.get(str(stage_at_date))
    if cfg is None or cfg['excluded']:
        return False

    return cfg['order'] >= cfg['qualified_stage_order']
