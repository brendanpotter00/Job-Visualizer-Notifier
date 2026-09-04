"""Retire the orphan ``project_manager`` category — all four coordinated items.

WHY THIS IS PHASE 1 AND REQUIRED, NOT A TIDY-UP
------------------------------------------------
The cross-repo taxonomy parity check goes red on day one without it. Verified
against the live schema and both repos:

* ``job_categories`` holds 7 seeded rows (``0fa33aca5bda``, ``project_manager``
  at sort_order 3);
* ``enrichment_writer.CATEGORY_SLUGS`` holds the same 7;
* the enricher's ``taxonomy.CATEGORIES`` already holds **6** — it dropped
  ``project_manager`` some time ago and nothing noticed, because every existing
  guard is intra-repo.

This epic is about to widen that surface from 6 slugs to 21. Closing the
existing drift first is what makes the new parity assertion meaningful instead
of permanently red.

FOUR COORDINATED ITEMS PLUS A PRE-FLIGHT, ONE REVISION
-------------------------------------------------------
**(a) PRE-FLIGHT, in ``upgrade()``.** ``job_listings.enrichment_category`` is a
real FK onto ``job_categories.slug`` (``db_models.py``), so a DELETE with live
references either FAILS or orphans. Any such row is NULLed first — the same
shape ``0b61e444ea25`` uses — and then the count is asserted to be 0.

**(b) SCRUB SAVED FILTERS, BEFORE the DELETE.**
``user_saved_filters.category`` is **JSONB**, not an FK column, so NOTHING WOULD
ERROR if this were skipped. The saved filter would simply keep selecting a slug
the facets endpoint no longer returns — a filter that silently matches nothing,
forever, with no signal anywhere. ``category - 'project_manager'`` removes the
element.

**(c) DELETE the dimension row**, exporting ``REMOVED_CATEGORIES`` for the
parity test to subtract (the ``ADDED_LEVELS`` pattern from ``0b61e444ea25``).

**(d) Drop it from ``CATEGORY_SLUGS`` (7 -> 6)** in
``services/enrichment_writer.py``, and update the parity assertion in
``test_internal_enrichment.py`` to subtract ``REMOVED_CATEGORIES`` — mirroring
how it already unions ``intern_mig.ADDED_LEVELS``. That half is a code change,
not SQL, and lives in this PR.

DEPLOY CONTEXT
--------------
``SET LOCAL lock_timeout = '5s'`` first in both directions (house rule,
unconditional). The UPDATE over ``user_saved_filters`` touches single-digit rows;
the ``job_listings`` NULLing is expected to touch ZERO (nothing has ever been
classified ``project_manager`` — the enricher's taxonomy has not contained it).

DOWNGRADE
---------
Re-inserts the dimension row at its original sort_order. It does NOT restore the
scrubbed saved filters or the NULLed listings — that information is gone, which
is stated here rather than pretended otherwise. It is safe in the sense that
matters: the FK target exists again, so a later re-classification would work.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e6f81ad4b57'
down_revision: Union[str, None] = 'b93d5c17a842'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Read by the taxonomy-parity test, which SUBTRACTS this from the base seed to
# stay in lock-step with the code constants — the mirror image of how
# 0b61e444ea25's ADDED_LEVELS is unioned in. (slug, label, sort_order) matches
# 0fa33aca5bda's CATEGORY_SEED tuple shape so downgrade can restore it verbatim.
REMOVED_CATEGORIES = ["project_manager"]

_RESTORE_ON_DOWNGRADE = [("project_manager", "Project Manager", 3)]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()

    # (a) PRE-FLIGHT: clear any live FK reference, then prove there is none.
    bind.execute(
        sa.text(
            "UPDATE job_listings SET enrichment_category = NULL "
            "WHERE enrichment_category = 'project_manager'"
        )
    )
    remaining = bind.execute(
        sa.text(
            "SELECT count(*) FROM job_listings "
            "WHERE enrichment_category = 'project_manager'"
        )
    ).scalar()
    assert remaining == 0, (
        f"{remaining} job_listings rows still reference 'project_manager' after "
        "the pre-flight NULLing — refusing to DELETE the FK target."
    )

    # (b) Scrub saved filters BEFORE the delete. JSONB, no FK, so nothing would
    #     have errored — the filter would just have matched nothing forever.
    bind.execute(
        sa.text(
            "UPDATE user_saved_filters SET category = category - 'project_manager' "
            "WHERE category ? 'project_manager'"
        )
    )

    # (c) The dimension row itself.
    bind.execute(
        sa.text("DELETE FROM job_categories WHERE slug = 'project_manager'")
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    for slug, label, sort_order in _RESTORE_ON_DOWNGRADE:
        bind.execute(
            sa.text(
                "INSERT INTO job_categories (slug, label, sort_order) "
                "VALUES (:slug, :label, :sort_order) ON CONFLICT (slug) DO NOTHING"
            ),
            {"slug": slug, "label": label, "sort_order": sort_order},
        )
