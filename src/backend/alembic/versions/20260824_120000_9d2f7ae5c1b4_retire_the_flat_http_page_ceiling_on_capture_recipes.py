"""retire the flat 100-page http ceiling on stored capture recipes

Revision ID: 9d2f7ae5c1b4
Revises: c4f0a91b2d73
Create Date: 2026-08-24 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — one UPDATE against ``company_scripts.script`` JSONB, so
``db_models.py`` and the Alembic-parity test are untouched.

Why
---
``c4f0a91b2d73`` (the previous revision) raised the legacy FLAT budget of 10 to a
flat ceiling of 100. That ceiling has now been deleted from the code, because a
flat PAGE ceiling is a different JOB ceiling on every board — the page size is
the board's choice, not ours:

===================  =========  ==============  ==================
board                page size  declared total  reachable at 100pp
===================  =========  ==============  ==================
amazon.jobs                100          10,000              10,000
Microsoft (Eightfold)       10           2,111               1,000
Walmart                     10          47,298               1,000
===================  =========  ==============  ==================

Microsoft was truncated at 47% of its own board by our constant and by nothing
about Microsoft, and then shown to its owner as "tracking part of this board".
Discovery now derives the stored budget from the board's own declared total and
the page size it PROVED, under a ceiling expressed in JOBS
(``recipe_runner.MAX_HARVEST_RECORDS`` / page_size), and the sweep is bounded at
runtime by a wall clock (``recipe_runner.HARVEST_TIME_BUDGET_S``) rather than by
anything baked into the recipe.

A row stored before this carries the retired ceiling. This migration raises it.

Why a migration, and not a read-time derivation
-----------------------------------------------
``max_pages`` is part of the recipe, and the recipe is re-validated on every
nightly READ (``validate_recipe``). Deriving the budget at read time would mean
the stored bytes no longer say what the run will do, which is exactly the drift
``validate_recipe``'s column-equality check exists to catch — and it would make
the browser tier's ceiling (asserted against the STORED value) unenforceable.
Re-discovery would also work but is not free: it costs a browser capture and an
LLM call per board, and it is the user who has to ask for it (Remove + re-add).
Rewriting the one field, exactly as ``c4f0a91b2d73`` did, keeps the recipe the
single source of truth for what a run will do.

Which rows move, and why raising is safe without proof
------------------------------------------------------
Only ``http_json`` / ``http_html`` rows whose ``max_pages`` is exactly the
retired ceiling — the value a clamped derivation, a no-declared-total board, or
``c4f0a91b2d73`` itself produced. A budget a discovery run derived BELOW the
ceiling was never truncated and is left alone.

Raising is safe and needs no acceptance replay, for the same reason it was last
time: the budget is a CEILING, not a target. ``recipe_runner._sweep_offset_page``
stops on the first short page, so a board smaller than the new number pays
exactly nothing for it. And the two new runtime bounds are what make a much
larger ceiling affordable — a sweep that runs long stops on the clock with
``cap_hit=True``, which ``verify_harvest`` reads as UNVERIFIED, so an unfinished
read still closes nothing (invariant #2).

``browser_fetch`` rows are NOT touched. Their ceiling (25) did not move — a page
there is a Chromium round-trip, and ``validate_recipe`` REJECTS a browser recipe
over it on every read, so raising one would store a row that FAILS every night.

What this still cannot fix, unchanged from ``c4f0a91b2d73``: the PAGE SIZE, the
``window_cap`` and the capped-declared-total oracle downgrade are all
acceptance-proven parameters derived from bytes this migration does not have. So
a 10-per-page legacy row comes out of this reading its whole board ten at a time
— correct, just slower than a re-discovered one.

``paginate_facet`` rows are left alone: their budget is per-facet
(``max_pages_per_facet``) and multiplies by the facet count, so the same number
does not mean the same thing.

Expected rowcounts on first run: ZERO in production — capture discovery has
never run there. The population this exists for is the local/dev rows.

Chain position: chains off the current single head ``c4f0a91b2d73``.
"""
import json
import logging
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = '9d2f7ae5c1b4'
down_revision: Union[str, None] = 'c4f0a91b2d73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The ceiling this migration RETIRES — the value ``c4f0a91b2d73`` wrote and the
# value a clamped derivation produced. Scoping the UPDATE to it (rather than
# "anything below the new ceiling") keeps this a targeted repair of one known
# constant instead of a blanket rewrite of budgets discovery derived on purpose.
_RETIRED_HTTP_CEILING = 100

# The replacement, in JOBS. Kept in sync with
# ``recipe_runner.MAX_HARVEST_RECORDS``; a literal rather than an import because a
# migration is a frozen historical fact and must not change meaning when the
# constant moves.
_MAX_HARVEST_RECORDS = 50_000

# Transports this migration may rewrite. ``browser_fetch`` is deliberately absent:
# its ceiling did not move and ``validate_recipe`` rejects a recipe above it.
_HTTP_TRANSPORTS = ('http_json', 'http_html')

_PAGINATION_OPS = ('paginate_offset', 'paginate_page')

_SELECT = sa.text(
    "SELECT company_id, transport, script FROM company_scripts"
)
_WRITE = sa.text(
    "UPDATE company_scripts SET script = CAST(:script AS jsonb), updated_at = now() "
    "WHERE company_id = :company_id"
)


def _new_budget(page_size: Any) -> int | None:
    """The job-denominated ceiling converted through this recipe's own page size.

    ``None`` for a page size we cannot divide by — a row we do not understand must
    be a no-op, never a crash that wedges the whole upgrade.
    """
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
        return None
    return max(1, _MAX_HARVEST_RECORDS // page_size)


def _rewrite(rows: Sequence[Any]) -> list[dict]:
    """Rows carrying the retired ceiling, rewritten, as ``{company_id, script}``.

    Read-modify-write in Python rather than a ``jsonb_set`` over a lateral
    ``jsonb_array_elements``: the step's ARRAY INDEX is what has to be addressed,
    Postgres will not let the UPDATE target appear in its own lateral FROM, and
    the workaround (a self-join subquery computing the index) is materially
    harder to read than the loop below for a table that holds one row per
    tracked custom company.
    """
    changed: list[dict] = []
    for company_id, transport, script in rows:
        if str(transport) not in _HTTP_TRANSPORTS or not isinstance(script, dict):
            continue
        steps = script.get('steps')
        if not isinstance(steps, list):
            continue
        touched = False
        for step in steps:
            if not isinstance(step, dict) or step.get('op') not in _PAGINATION_OPS:
                continue
            if step.get('max_pages') != _RETIRED_HTTP_CEILING:
                continue
            budget = _new_budget(step.get('page_size'))
            # Never LOWER a stored budget. A 500-per-page recipe would derive 100,
            # which is the number we are retiring — writing it back would be a no-op
            # that reads like a repair.
            if budget is None or budget <= _RETIRED_HTTP_CEILING:
                continue
            step['max_pages'] = budget
            touched = True
        if touched:
            changed.append({'company_id': company_id, 'script': json.dumps(script)})
    return changed


def upgrade() -> None:
    bind = op.get_bind()
    changed = _rewrite(bind.execute(_SELECT).fetchall())
    for row in changed:
        bind.execute(_WRITE, row)
    # Logged, never asserted: zero rows is the EXPECTED prod outcome (discovery
    # has never run there), but a silent no-op is how a broken repair ships
    # looking like a completed one, so the count is always reported.
    logger.info(
        "retired the flat http page ceiling on %d capture recipe(s)", len(changed)
    )


def downgrade() -> None:
    """Deliberate NO-OP, for the same reason ``c4f0a91b2d73``'s downgrade is one.

    The inverse — put 100 back wherever ``max_pages`` equals the job-denominated
    ceiling — cannot tell a row this migration raised from one a LATER discovery
    run derived at exactly that number, and re-imposing 100 is precisely the
    truncation this revision exists to undo.

    Stated honestly, because it is NOT free: rolled-back CODE has no mid-sweep
    clock, so a raised budget on a huge board would sweep until the leaf task's
    (also rolled-back, 120s) timeout fires. That is a FAILED run — it writes
    nothing, closes nothing and is not a miss — so the board goes STALE rather
    than losing jobs, which is the safe direction of the two. Every board small
    enough to have fit the old ceiling still terminates on its short page exactly
    as before. Trading a stale huge board against silently corrupting a
    correctly-derived recipe is not a close call.
    """
    logger.info(
        "no-op downgrade: a raised page budget is indistinguishable from a derived "
        "one and reverting it would re-truncate the boards this revision repaired"
    )
