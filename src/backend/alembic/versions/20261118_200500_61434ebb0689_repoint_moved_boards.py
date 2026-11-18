"""repoint moved job boards detected by scraper-health-watch on 2026-11-18

Revision ID: 61434ebb0689
Revises: 55feada2eb2c
Create Date: 2026-11-18 20:05:00.000000

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — UPDATEs against ``companies`` / ``job_listings`` only,
so ``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
boltz (Boltz — molecular design for drug discovery) moved its job board from Gem
to Ashby. Its Gem board ``jobs.gem.com/boltz`` is still *alive* but has been
drained to zero postings: the posting API answers HTTP 200 with a literal empty
array ``[]`` (3 bytes). The roles did not disappear — all 12 of them are now on
Ashby at ``jobs.ashbyhq.com/boltz``, including "Senior Scientist, Small
Molecule", "Senior Scientist, Biologics", "Senior Scientist, Cheminformatics"
and "Product Designer, Boltz Lab", which identify the company unambiguously.

The drain is visible in ``scrape_runs``: boltz served 14 jobs/run through
2026-11-13, dropped to 3 on 2026-11-14/15, and has returned 0 on every run since
2026-11-16 (48/48 runs on 2026-11-17, 41/41 so far on 2026-11-18, each one
``error_count=1`` and ``skipped_update=true`` with ``guard_reason=empty_scrape``).
The 12 live Ashby postings against the 14 it last served on Gem is a near-exact
match, which is the corroboration that this is a migration and not two different
companies sharing a slug.

This shape is why a live-but-empty board must still be guess-probed across the
other providers. The ``empty_scrape`` guard latch is correct — the scraper agrees
with the Gem board — so the board-empty branch alone would have read this as
"Boltz stopped hiring" indefinitely, while the roles were on Ashby the whole
time. The 404 that normally marks a move never came, because the old board was
emptied rather than deleted.

Verified live API results at authoring time (2026-11-18)
---------------------------------------------------------
old  https://api.gem.com/job_board/v0/boltz/job_posts/          -> 200, 3 B, `[]` (0 jobs)
new  https://api.ashbyhq.com/posting-api/job-board/boltz        -> 200, 171953 B, 12 jobs
neg  https://api.gem.com/job_board/v0/zzz-not-a-real-board-9f3/job_posts/ -> 404
neg  https://api.ashbyhq.com/posting-api/job-board/zzz-not-a-real-board-9f3 -> 404
pos  https://api.gem.com/job_board/v0/retool/job_posts/         -> 200, 402607 B (real posts)

The two negative controls are what make the old board's 200 meaningful: Gem and
Ashby both 404 an unknown token, so boltz's Gem 200-with-`[]` is a real board
that is genuinely empty, not a misread of a dead endpoint.

Candidates probed and rejected (all HTTP 404): greenhouse/boltz,
lever/boltz, greenhouse|ashby|lever/{boltz-ai, boltzbio, boltzai}.

New-provider ids land under a different ``source_id`` than the stale rows
(composite PK ``(source_id, id)``), so incoming rows can never collide with or
dedupe against the old ones. That is exactly why the stale rows must be closed
here rather than left to age out.

Chain position
--------------
Chains off the current single head ``55feada2eb2c`` (the 2026-11-17 browserbase
repoint). Frozen per-ATS seed migrations are never edited — a provider change is
a new event, expressed as a new migration.

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
boltz: 1 ``companies`` row repointed (gem/boltz -> ashby/boltz); 3 stale
``gem_api`` ``job_listings`` rows closed (11 more are already CLOSED and are not
re-touched — the status='OPEN' scope excludes them).

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched — Ashby needs none.
- ``closed_on`` uses the FIXED sentinel ``_BACKFILL_CLOSED_ON`` (never
  ``now()``) so ``downgrade()`` re-opens EXACTLY the rows this migration closed.
  Verified read-only that the latest pre-existing ``closed_on`` for boltz's
  ``gem_api`` rows is 2026-11-14T00:30:13Z, earlier than the sentinel, so the
  sentinel cannot collide with a row closed by a real scrape.
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
revision: str = '61434ebb0689'
down_revision: Union[str, None] = '55feada2eb2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after). old_source_id = '<old_ats>_api'.
REPOINTED = [
    {'id': 'boltz', 'old_ats': 'gem', 'old_token': 'boltz',
     'new_ats': 'ashby', 'new_token': 'boltz', 'old_source_id': 'gem_api'},
]
# Companies soft-disabled because the destination is unsupported/gone
# (unity3d precedent: row + history preserved, fully reversible).
DISABLED = [
    # {'id': '...', 'reason': '...'},
]
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Must be later than every pre-existing closed_on
# for the affected companies — verified with a read-only MAX(closed_on) query
# (boltz/gem_api max was 2026-11-14T00:30:13Z).
_BACKFILL_CLOSED_ON = '2026-11-18T00:00:00+00:00'


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
