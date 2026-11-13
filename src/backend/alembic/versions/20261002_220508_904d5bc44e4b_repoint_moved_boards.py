"""repoint moved job boards detected by scraper-health-watch on 2026-10-02

Revision ID: 904d5bc44e4b
Revises: ba0bdd5e978b
Create Date: 2026-10-02 22:05:00.000000

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — UPDATEs against ``companies`` / ``job_listings`` only,
so ``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
``hightouch`` (Hightouch) migrated off Greenhouse to Ashby. The Greenhouse board
served 82 jobs as recently as 2026-10-02T20:32Z and then went hard 404: every
run from 21:02Z onward recorded ``jobs_seen=0, error_count=1``, which is the
silent-zero signature Check A2 fires on. The old token is gone, not empty —
``https://boards-api.greenhouse.io/v1/boards/hightouch/jobs`` answers
``{"status":404,"error":"Job not found"}``, and the ``Hightouch`` and
``hightouchio`` spellings 404 as well.

The live board is Ashby under the token ``hightouch-inc``, which serves 82
jobs — the same count as the 82 OPEN ``greenhouse_api`` rows frozen in prod and
the same count as the 82 ``/careers/<uuid>`` links on hightouch.com/careers.
The token was not guessed: it came out of the apply link on a careers detail
page (``https://jobs.ashbyhq.com/hightouch-inc/<posting-uuid>``), and the
departments (Engineering 18, Sales 15, Customer Success 13, Technical Sales 10,
AI 6) plus the publish dates (64 of 82 posted in 2026) corroborate it.

TRAP, recorded so the next reader does not repeat the probe: the bare Ashby
token ``hightouch`` ALSO answers HTTP 200 — with exactly one posting, "Backend
Engineer, Platform", published 2021-03-16 and describing "a close-knit team of
13" that "just raised a Series A". That is Hightouch's abandoned 2021 Ashby
board, left listed and never cleaned up. It is a false positive for a
200-with-jobs probe and must NOT be used; ``hightouch-inc`` is the live board.

Verified live API results at authoring time (2026-10-02)
-------------------------------------------------------
old  https://boards-api.greenhouse.io/v1/boards/hightouch/jobs?content=true
       -> HTTP 404  {"status":404,"error":"Job not found"}
old  https://boards-api.greenhouse.io/v1/boards/hightouch/jobs
       -> HTTP 404  (retry without content param)
old  https://boards-api.greenhouse.io/v1/boards/Hightouch/jobs     -> HTTP 404
old  https://boards-api.greenhouse.io/v1/boards/hightouchio/jobs   -> HTTP 404
new  https://api.ashbyhq.com/posting-api/job-board/hightouch-inc
       -> HTTP 200, jobs=82, apiVersion=1
bad  https://api.ashbyhq.com/posting-api/job-board/hightouch
       -> HTTP 200, jobs=1 (stale 2021 board — see TRAP above)
ref  https://hightouch.com/careers -> 82 /careers/<uuid> links; a detail page's
       apply link is https://jobs.ashbyhq.com/hightouch-inc/<same-uuid>
neg  https://api.lever.co/v0/postings/hightouch?mode=json           -> HTTP 404
neg  https://api.gem.com/job_board/v0/hightouch/job_posts/          -> HTTP 404
neg  https://api.smartrecruiters.com/v1/companies/hightouch/postings
       -> HTTP 200 content=0 (unknown company, not a hit)

New-provider ids land under a different ``source_id`` than the stale rows
(composite PK ``(source_id, id)``), so incoming rows can never collide with or
dedupe against the old ones. That is exactly why the stale rows must be closed
here rather than left to age out. Ashby posting ids are UUIDs and Greenhouse
ids are integers, so the two id spaces could not overlap even on one source_id.

Chain position
--------------
Chains off the current single head ``ba0bdd5e978b``
(``20260927_055222_ba0bdd5e978b_seed_firecrawl_company.py``). Frozen per-ATS
seed migrations are never edited — a provider change is a new event, expressed
as a new migration.

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
hightouch: 1 ``companies`` row repointed (greenhouse/hightouch ->
ashby/hightouch-inc), 82 stale ``greenhouse_api`` OPEN ``job_listings`` rows
closed. From live read-only SELECT count(*) at authoring time: the company has
134 rows total — 82 OPEN and 52 already CLOSED, all under ``greenhouse_api``.

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched — Ashby needs none.
- ``closed_on`` uses the FIXED sentinel ``_BACKFILL_CLOSED_ON`` (never
  ``now()``) so ``downgrade()`` re-opens EXACTLY the rows this migration closed.
  Verified read-only that no existing hightouch row carries that exact value
  (0 collisions). The company's current MAX(closed_on) is
  2026-10-02T00:02:10.552Z — two minutes after the sentinel but not equal to it,
  so the sentinel match stays unambiguous and the 52 rows closed by real scrapes
  cannot be re-opened by a downgrade.
- The close-out is triple-scoped (company literal AND old source_id AND
  status='OPEN') so it cannot touch other companies, incoming rows, or
  already-closed rows.
- All operations are idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` entry moved to the Ashby section) and
the ``changelog.ts`` announcement ship in the same PR.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = '904d5bc44e4b'
down_revision: Union[str, None] = 'ba0bdd5e978b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after). old_source_id = '<old_ats>_api'.
REPOINTED = [
    {'id': 'hightouch', 'old_ats': 'greenhouse', 'old_token': 'hightouch',
     'new_ats': 'ashby', 'new_token': 'hightouch-inc',
     'old_source_id': 'greenhouse_api'},
]
# Companies soft-disabled because the destination is unsupported/gone
# (unity3d precedent: row + history preserved, fully reversible).
DISABLED = [
]
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Verified against MAX(closed_on) for the affected
# company — see the docstring.
_BACKFILL_CLOSED_ON = '2026-10-02T00:00:00+00:00'


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
