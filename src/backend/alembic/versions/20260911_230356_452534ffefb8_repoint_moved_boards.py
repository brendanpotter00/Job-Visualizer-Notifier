"""repoint moved job boards detected by scraper-health-watch on 2026-09-11

Revision ID: 452534ffefb8
Revises: 8cb48c74a166
Create Date: 2026-09-11 23:03:56

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — an UPDATE against ``companies`` only, so
``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
resolve-ai (Resolve AI) renamed its Ashby job-board slug. Our stored
``board_token`` is the literal ``Resolve AI``; as of 2026-09-11 ~19:33Z that
token 404s on the Ashby posting API under every encoding, and every scrape run
since has returned ``jobs_seen = 0`` with ``error_count = 1`` (78 runs in 24h,
36 of them errored). The same board is live at the slug ``resolveai`` with 14
listed jobs — byte-identical to the 14 rows we already hold OPEN for this
company.

Verified live API results at authoring time (2026-09-11)
--------------------------------------------------------
- ``https://api.ashbyhq.com/posting-api/job-board/Resolve%20AI`` -> 404 Not Found
- ``https://api.ashbyhq.com/posting-api/job-board/Resolve+AI``   -> 404 Not Found
- ``https://api.ashbyhq.com/posting-api/job-board/resolve-ai``   -> 404 Not Found
- ``https://api.ashbyhq.com/posting-api/job-board/resolveai``    -> 200, 14 jobs
- ``https://jobs.ashbyhq.com/resolveai``                         -> 200

Why there is NO stale-row close-out here
----------------------------------------
The template this migration is copied from closes the old provider's rows
because a cross-provider move lands the new rows under a different
``source_id`` (composite PK ``(source_id, id)``), so old and new can never
dedupe against each other. That reasoning does not apply to a same-ATS slug
rename: ``source_id`` stays ``ashby_api`` AND the 14 live Ashby job UUIDs are
exactly the 14 UUIDs already OPEN in ``job_listings`` (set-compared against the
live API at authoring time — identical, no additions, no removals). Closing
them would close 14 genuinely-open roles that the very next scrape re-reports.
So ``REPOINTED`` carries ``close_stale_source_id = None`` and the close-out is
skipped. Keep that flag ``None`` for any future same-ATS token change.

Chain position
--------------
Chains off the current single head ``8cb48c74a166`` (verified with
``alembic heads``).

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
- resolve-ai: 1 ``companies`` row repointed, 0 ``job_listings`` rows closed.

- ``ats`` is unchanged (``ashby`` before and after) — only ``board_token`` moves.
- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched.
- All operations are idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` board URL) and the ``changelog.ts``
announcement ship in the same PR.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = '452534ffefb8'
down_revision: Union[str, None] = '8cb48c74a166'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after). ``close_stale_source_id`` is the old
# provider's source_id when the move changes provider, and None for a same-ATS
# token rename (see the module docstring — closing the rows would close live
# jobs that carry the identical ids under the identical source_id).
REPOINTED = [
    {
        'id': 'resolve-ai',
        'old_ats': 'ashby',
        'old_token': 'Resolve AI',
        'new_ats': 'ashby',
        'new_token': 'resolveai',
        'close_stale_source_id': None,
    },
]
# Companies soft-disabled because the destination is unsupported/gone
# (unity3d precedent: row + history preserved, fully reversible).
DISABLED = []
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Unused while every REPOINTED row has
# close_stale_source_id = None, but kept so the close-out path stays correct
# the next time a real provider move batches through here.
_BACKFILL_CLOSED_ON = '2026-09-11T00:00:00+00:00'


def upgrade() -> None:
    bind = op.get_bind()
    repoint = sa.text(
        "UPDATE companies SET ats = :new_ats, board_token = :new_token WHERE id = :id"
    )
    close_stale = sa.text(
        "UPDATE job_listings SET status = 'CLOSED', "
        "closed_on = CAST(:closed_on AS timestamptz) "
        "WHERE company = :id AND source_id = :source_id AND status = 'OPEN'"
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
        if row['close_stale_source_id'] is None:
            logger.info(
                "backfill: skipped for %s — same-ATS token rename, live ids "
                "match the rows already OPEN under source_id=%s_api",
                row['id'], row['old_ats'],
            )
            continue
        closed = bind.execute(
            close_stale,
            {
                'id': row['id'],
                'source_id': row['close_stale_source_id'],
                'closed_on': _BACKFILL_CLOSED_ON,
            },
        )
        logger.info(
            "backfill: closed %d stale %s rows for %s",
            closed.rowcount, row['close_stale_source_id'], row['id'],
        )

    for row in DISABLED:
        disabled = bind.execute(
            sa.text("UPDATE companies SET enabled = FALSE WHERE id = :id"),
            {'id': row['id']},
        )
        if disabled.rowcount == 0:
            logger.warning(
                "deactivate: no companies row matched id=%s — still enabled",
                row['id'],
            )
        else:
            logger.info(
                "deactivate: %s enabled=FALSE (%s)", row['id'], row['reason']
            )


def downgrade() -> None:
    # Exact inverse, in reverse order. The closed_on sentinel match makes the
    # re-open surgical: rows closed by a real scrape stay CLOSED.
    bind = op.get_bind()
    for row in DISABLED:
        bind.execute(
            sa.text("UPDATE companies SET enabled = TRUE WHERE id = :id"),
            {'id': row['id']},
        )
    reopen = sa.text(
        "UPDATE job_listings SET status = 'OPEN', closed_on = NULL "
        "WHERE company = :id AND source_id = :source_id AND status = 'CLOSED' "
        "AND closed_on = CAST(:closed_on AS timestamptz)"
    )
    unrepoint = sa.text(
        "UPDATE companies SET ats = :old_ats, board_token = :old_token WHERE id = :id"
    )
    for row in REPOINTED:
        if row['close_stale_source_id'] is not None:
            bind.execute(
                reopen,
                {
                    'id': row['id'],
                    'source_id': row['close_stale_source_id'],
                    'closed_on': _BACKFILL_CLOSED_ON,
                },
            )
        bind.execute(
            unrepoint,
            {'id': row['id'], 'old_ats': row['old_ats'], 'old_token': row['old_token']},
        )
