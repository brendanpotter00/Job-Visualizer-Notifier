"""repoint moved job boards detected by scraper-health-watch on 2026-09-23

Revision ID: 593e96381b3e
Revises: c48b0f2e7d19
Create Date: 2026-09-23 04:05:38.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — an UPDATE against ``companies`` only, so
``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
Workweave rebranded to **Weave / WeaveOS** and moved its Ashby board from slug
``workweave`` to ``weave-os``. The old board went dead between the 01:33Z and
02:03Z ticks on 2026-09-23: every scrape from 02:03Z onward is a 6-row error
storm with ``jobs_seen = 0`` (the classic 404-storm signature), and
``https://api.ashbyhq.com/posting-api/job-board/workweave`` now returns HTTP
404 "Not Found". The company is very much alive — ``weaveos.com`` links its
careers page straight at ``jobs.ashbyhq.com/weave-os``, and the new board
serves the same 12 roles.

The ATS does **not** change: ashby -> ashby. Only ``board_token`` moves.

Verified live API results at authoring time (2026-09-23)
--------------------------------------------------------
    https://api.ashbyhq.com/posting-api/job-board/workweave
        -> HTTP 404, body "Not Found"                       (old board, dead)
    https://api.ashbyhq.com/posting-api/job-board/weave-os
        -> HTTP 200, apiVersion 1, 12 jobs                  (new board, live)
    https://weaveos.com/
        -> careers href resolves to jobs.ashbyhq.com/weave-os
    LinkedIn company id 102726930 (the id already recorded on our
    ``workweave`` entry in companies.ts) now resolves to "Weave".

    Corroboration — the 12 live postings on ``weave-os`` carry the SAME Ashby
    posting UUIDs as our 12 frozen OPEN rows, e.g.
        Field CTO                 3b08840b-6056-4d11-9330-7ae6c490cd35
        Founding ML Engineer      74d1292b-2397-49e8-acdc-f8e211a985d5
        Forward Deployed Engineer 60226f73-954c-421c-b609-c377255b062e
    Only the slug in the URL changed (``/workweave/<uuid>`` ->
    ``/weave-os/<uuid>``). This is the same board under a new name, not a
    different board that happens to look similar.

    Deliberately NOT used — token collision. ``ashby/weave`` and
    ``greenhouse/weave`` both answer HTTP 200 but belong to the unrelated
    Weave Communications (dental SaaS, Lehi UT, 29 postings). ``weave-os`` is
    the correct token.

Why there is NO stale-row close-out here (deviation from the template)
----------------------------------------------------------------------
The repoint template closes the old rows because a cross-ATS move lands the
incoming jobs under a *different* ``source_id``, and the composite PK
``(source_id, id)`` would otherwise leave the old rows orphaned and OPEN
forever.

That premise does not hold for this migration. The ATS is unchanged, so the
incoming rows keep ``source_id = 'ashby_api'`` AND keep their posting UUIDs —
they collide with our existing rows on the full composite PK and are refreshed
in place by ``_UPSERT_ON_CONFLICT`` (``scripts/shared/database.py:156``), which
sets ``url = EXCLUDED.url``, ``status = 'OPEN'``, ``closed_on = NULL``. The 12
frozen rows therefore self-heal on the first successful tick, including their
stale ``/workweave/`` URLs, because the Ashby client takes ``url`` verbatim
from the API's ``jobUrl`` (``ashby_client.py:119``).

Closing them here would be worse than a no-op: it would flip 12 currently-live
roles to CLOSED, emit 12 spurious closure events, and then the very next scrape
would re-open all 12 via that same ON CONFLICT clause. So this migration
repoints the company row and stops there.

Chain position
--------------
Chains off the current single head ``c48b0f2e7d19``. Frozen per-ATS seed
migrations are never edited — a provider change is a new event, expressed as a
new migration.

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
    workweave: 1 ``companies`` row repointed (ashby/workweave ->
    ashby/weave-os). 0 ``job_listings`` rows touched by this migration; the 12
    OPEN rows are left for the scraper to refresh in place (see above).

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched (Ashby needs none; prod has ``{}``).
- ``enabled`` is NOT touched — the company stays enabled throughout.
- All operations are idempotent and safe to re-run.

The frontend counterpart (the ``companies.ts`` board URL) and the
``changelog.ts`` announcement ship in the same PR. The company ``id`` and its
``COMPANY_IDS`` member deliberately do NOT change: they are the primary key and
the logo lookup key.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = '593e96381b3e'
down_revision: Union[str, None] = 'c48b0f2e7d19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after).
#
# No ``old_source_id`` key and no close-out: this is a same-ATS slug change, so
# the incoming rows reuse the existing composite PK and refresh in place. See
# the module docstring.
REPOINTED = [
    {
        'id': 'workweave',
        'old_ats': 'ashby',
        'old_token': 'workweave',
        'new_ats': 'ashby',
        'new_token': 'weave-os',
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    repoint = sa.text(
        "UPDATE companies SET ats = :new_ats, board_token = :new_token WHERE id = :id"
    )
    # Rowcounts are logged, not asserted: a no-op is legitimate (fresh DB or
    # re-run), but a SILENT no-op is how a drifted id ships as "migrated" while
    # the board stays dead — so every statement reports what it touched.
    for row in REPOINTED:
        res = bind.execute(
            repoint,
            {'id': row['id'], 'new_ats': row['new_ats'], 'new_token': row['new_token']},
        )
        if res.rowcount == 0:
            logger.warning(
                "repoint: no companies row matched id=%s — board NOT repointed",
                row['id'],
            )
        else:
            logger.info(
                "repoint: %s -> %s/%s (%d row)",
                row['id'], row['new_ats'], row['new_token'], res.rowcount,
            )


def downgrade() -> None:
    # Exact inverse. Nothing to re-open: upgrade() closed no listings.
    bind = op.get_bind()
    unrepoint = sa.text(
        "UPDATE companies SET ats = :old_ats, board_token = :old_token WHERE id = :id"
    )
    for row in REPOINTED:
        bind.execute(
            unrepoint,
            {'id': row['id'], 'old_ats': row['old_ats'], 'old_token': row['old_token']},
        )
