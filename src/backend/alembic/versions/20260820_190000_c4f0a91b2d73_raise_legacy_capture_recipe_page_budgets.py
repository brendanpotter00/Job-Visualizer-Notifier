"""raise the legacy flat page budget on already-stored capture recipes

Revision ID: c4f0a91b2d73
Revises: fb8467065dfc
Create Date: 2026-08-20 19:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — one UPDATE against ``company_scripts.script`` JSONB, so
``db_models.py`` and the Alembic-parity test are untouched.

Why
---
Capture discovery used to bake a FLAT ``paginate_*.max_pages = 10`` into every
recipe it stored, and that same constant was ALSO the acceptance budget — one
number doing two jobs. On a board whose own UI pages ten at a time that is a
97-job sample of a 22,000-job board: ``verify_harvest`` can never prove the run
saw the whole thing, so the company sits at ``health_state='unverified'``
forever and the user sees a sliver of the board. Discovery now derives the
stored budget from the board's own declared total and the page size it PROVED at
acceptance (``capture/discover._harvest_max_pages``).

What this migration can and cannot fix
--------------------------------------
It raises ``max_pages`` on recipes stored by the old code, and nothing else.

* Raising the budget is SAFE and needs no proof. The budget is a CEILING, not a
  target: ``recipe_runner._sweep_offset_page`` stops on the first short page, so
  a board smaller than the new budget pays exactly nothing for it, and a board
  bigger than the old one simply gets read further. Every extra page goes
  through the same 2xx / in-band-error / records-path / page-advance checks as
  the first, so RAISES-never-empty is unchanged.
* Raising the PAGE SIZE is NOT migratable. A bigger page size is a claim about
  the board that only an acceptance replay can settle — a board that ignores the
  parameter answers with a short page, and a short page is how the sweep decides
  the board ENDED, which would report a partial board as a complete one. Same
  for the ``window_cap`` and for the capped-declared-total oracle downgrade:
  both are DERIVED at discovery from bytes this migration does not have.

So a legacy row comes out of this reading its whole board at its own captured
page size, still UNVERIFIED if that page size cannot reach the board's total
within the ceiling. Re-discovery (Remove + re-add the careers URL, which is one
browser capture and one Haiku call) is what buys the derived page size, the
window cap and the corrected oracle. That is deliberate: those three are
acceptance-proven parameters and there is no honest way to conjure them from a
stored row.

Ceilings mirror the code exactly
--------------------------------
``_MAX_HARVEST_PAGES`` (100) for the http tiers; ``BROWSER_FETCH_MAX_PAGES``
(25) for ``browser_fetch``, where every page is a fresh in-browser ``fetch()``
inside one 90s Chromium session — and where ``validate_recipe`` now REJECTS a
recipe over that ceiling on read, so a migration that ignored the transport
would store rows that FAIL every night.

``paginate_facet`` rows are left alone: their budget is per-facet
(``max_pages_per_facet``) and multiplies by the facet count, so the same number
does not mean the same thing.

Expected rowcounts on first run: ZERO in production — capture discovery has
never run there. The population this exists for is the local/dev rows stored by
the old constant.

Chain position: chains off the current single head ``fb8467065dfc``.
"""
import json
import logging
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = 'c4f0a91b2d73'
down_revision: Union[str, None] = 'fb8467065dfc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with ``capture/discover._MAX_HARVEST_PAGES`` and
# ``recipe_schema.BROWSER_FETCH_MAX_PAGES``. Literals rather than imports: a
# migration is a frozen historical fact and must not change meaning when the
# constants move.
_HTTP_CEILING = 100
_BROWSER_FETCH_CEILING = 25

# The flat budget the old ``capture/discover._MAX_PAGES`` wrote. Scoping the
# UPDATE to it (rather than "anything below the ceiling") keeps the migration a
# targeted repair of one known constant instead of a blanket rewrite of budgets
# a later discovery run derived on purpose.
_LEGACY_FLAT_MAX_PAGES = 10

_PAGINATION_OPS = ('paginate_offset', 'paginate_page')

_SELECT = sa.text(
    "SELECT company_id, transport, script FROM company_scripts"
)
_WRITE = sa.text(
    "UPDATE company_scripts SET script = CAST(:script AS jsonb), updated_at = now() "
    "WHERE company_id = :company_id"
)


def _ceiling(transport: str) -> int:
    return _BROWSER_FETCH_CEILING if transport == 'browser_fetch' else _HTTP_CEILING


def _rewrite(rows: Sequence[Any]) -> list[dict]:
    """Rows carrying the legacy flat budget, rewritten, as ``{company_id, script}``.

    Read-modify-write in Python rather than a ``jsonb_set`` over a lateral
    ``jsonb_array_elements``: the step's ARRAY INDEX is what has to be addressed,
    Postgres will not let the UPDATE target appear in its own lateral FROM, and
    the workaround (a self-join subquery computing the index) is materially
    harder to read than the loop below for a table that holds one row per
    tracked custom company.
    """
    changed: list[dict] = []
    for company_id, transport, script in rows:
        if not isinstance(script, dict):
            continue
        steps = script.get('steps')
        if not isinstance(steps, list):
            continue
        ceiling = _ceiling(str(transport))
        touched = False
        for step in steps:
            if not isinstance(step, dict) or step.get('op') not in _PAGINATION_OPS:
                continue
            if step.get('max_pages') == _LEGACY_FLAT_MAX_PAGES:
                step['max_pages'] = ceiling
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
        "raised the legacy flat page budget on %d capture recipe(s)", len(changed)
    )


def downgrade() -> None:
    """Deliberate NO-OP. Verified: a symmetric downgrade corrupts good rows.

    The obvious inverse — put the flat 10 back wherever ``max_pages`` equals the
    ceiling — cannot tell a row this migration raised from one a LATER discovery
    run derived at exactly the ceiling (which is what amazon.jobs derives:
    ``ceil(10000/100) + 2``, clamped to 100). Measured on a throwaway DB seeded
    with both: the symmetric downgrade cut a correctly-derived 100-page budget
    back to 10, i.e. re-created the 97-job bug on a recipe that never had it.

    Leaving the raised budget in place is harmless in the other direction: the
    budget is a ceiling and the sweep stops on the first short page, so an
    un-downgraded row behaves exactly as it did before the rollback for every
    board small enough for the old budget. No data is lost and nothing is
    unreachable, so there is nothing here worth trading a corrupted recipe for.
    """
    logger.info(
        "no-op downgrade: a raised page budget is indistinguishable from a derived "
        "one and reverting it would truncate correctly-derived recipes"
    )
