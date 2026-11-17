"""repoint moved job boards detected by scraper-health-watch on 2026-11-17

Revision ID: 55feada2eb2c
Revises: 44a794f6649b
Create Date: 2026-11-17 08:00:00.000000

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — UPDATEs against ``companies`` / ``job_listings`` only,
so ``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
browserbase (Browserbase) moved its job board off Ashby to Greenhouse. The Ashby
board was **deleted**, not drained: the posting API returns a hard HTTP 404 for
token ``browserbase``, byte-identical to a bogus-token control, so this is
unambiguously a board move and not a company that stopped hiring. The break is
sharply dated — the 07:00:45Z tick on 2026-11-17 returned 9 jobs with
``error_count = 0``, and from 07:30Z every tick is a 404 storm (~6 error rows per
tick, ``jobs_seen = 0``). The board is now live at Greenhouse token
``browserbaseinc`` (NOT ``browserbase``, which 404s on Greenhouse too) serving 16
jobs under ``company_name: "Browserbase"``.

Verified live API results at authoring time (2026-11-17)
--------------------------------------------------------
======================================================================  ==========================
Endpoint                                                                Result
======================================================================  ==========================
https://api.ashbyhq.com/posting-api/job-board/browserbase               404 (x3, persistent)
https://api.ashbyhq.com/posting-api/job-board/ramp     (POS control)    200, 179 jobs
https://api.ashbyhq.com/posting-api/job-board/zzz-bogus-xyz9 (NEG)      404
https://boards-api.greenhouse.io/v1/boards/browserbaseinc/jobs          200, **16 jobs**
https://boards-api.greenhouse.io/v1/boards/browserbase/jobs             404
https://boards-api.greenhouse.io/v1/boards/airbnb/jobs (POS control)    200, 207 jobs
https://boards-api.greenhouse.io/v1/boards/zzz-bogus-xyz9/jobs (NEG)    404
https://api.lever.co/v0/postings/browserbase?mode=json                  404
https://api.gem.com/job_board/v0/browserbase/job_posts/                 404
======================================================================  ==========================

Identity corroboration (not just "a board that answers 200"): the Greenhouse
payload carries ``company_name: "Browserbase"``, ``absolute_url`` under
``job-boards.greenhouse.io/browserbaseinc/``, and its titles line up with the 9
frozen Ashby OPEN rows — Content Lead, Sales Engineer, Software Engineer (Agent
Platform), Technical Customer Success Manager, Account Executive, Recruiter. 16
live jobs against 9 frozen rows is well inside the ~3x corroboration band.

New-provider ids land under a different ``source_id`` than the stale rows
(composite PK ``(source_id, id)``), so incoming ``greenhouse_api`` rows can never
collide with or dedupe against the old ``ashby_api`` ones. That is exactly why the
stale rows must be closed here rather than left to age out.

Chain position
--------------
Chains off the current single head ``44a794f6649b``. Frozen per-ATS seed
migrations are never edited — a provider change is a new event, expressed as a
new migration.

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
browserbase: 1 ``companies`` row repointed (ashby/browserbase ->
greenhouse/browserbaseinc), 9 stale ``ashby_api`` ``job_listings`` rows closed.
From live read-only counts at authoring time: 9 OPEN + 11 already-CLOSED
``ashby_api`` rows, whose ``max(closed_on)`` is 2026-10-06 — comfortably before
the sentinel below, so ``downgrade()`` cannot re-open a row it did not close.

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched — Greenhouse needs none.
- ``closed_on`` uses the FIXED sentinel ``_BACKFILL_CLOSED_ON`` (never
  ``now()``) so ``downgrade()`` re-opens EXACTLY the rows this migration closed.
- The close-out is triple-scoped (company literal AND old source_id AND
  status='OPEN') so it cannot touch other companies, incoming rows, or
  already-closed rows.
- All operations are idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` entry moved to Greenhouse with the new
``sourceAts`` and board URL) and the ``changelog.ts`` announcement ship in the
same PR.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = '55feada2eb2c'
down_revision: Union[str, None] = '44a794f6649b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after). old_source_id = '<old_ats>_api'.
REPOINTED = [
    {'id': 'browserbase', 'old_ats': 'ashby', 'old_token': 'browserbase',
     'new_ats': 'greenhouse', 'new_token': 'browserbaseinc',
     'old_source_id': 'ashby_api'},
]
# Companies soft-disabled because the destination is unsupported/gone
# (unity3d precedent: row + history preserved, fully reversible).
DISABLED = []
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Must be later than every pre-existing closed_on
# for the affected companies — verified read-only: max(closed_on) for
# browserbase/ashby_api is 2026-10-06T05:00:35Z.
_BACKFILL_CLOSED_ON = '2026-11-17T00:00:00+00:00'


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
        closed = bind.execute(
            close_stale,
            {
                'id': row['id'],
                'source_id': row['old_source_id'],
                'closed_on': _BACKFILL_CLOSED_ON,
            },
        )
        logger.info(
            "backfill: closed %d stale %s rows for %s",
            closed.rowcount, row['old_source_id'], row['id'],
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
        bind.execute(
            reopen,
            {
                'id': row['id'],
                'source_id': row['old_source_id'],
                'closed_on': _BACKFILL_CLOSED_ON,
            },
        )
        bind.execute(
            unrepoint,
            {'id': row['id'], 'old_ats': row['old_ats'], 'old_token': row['old_token']},
        )
