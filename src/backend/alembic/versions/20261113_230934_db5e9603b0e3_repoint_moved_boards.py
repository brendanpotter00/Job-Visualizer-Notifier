"""repoint moved job boards detected by scraper-health-watch on 2026-11-13

Revision ID: db5e9603b0e3
Revises: a1d81f01341f
Create Date: 2026-11-13 23:09:34.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — UPDATEs against ``companies`` / ``job_listings`` only,
so ``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
shield-ai (Shield AI) moved from Lever to Ashby on 2026-11-13. The Lever board
``shieldai`` was not deleted — it was *drained*, which is why nothing 404s and
why the watchdog's usual "board moved" signature (HTTP 404) never appeared. The
drain is visible run-by-run in ``scrape_runs`` over a single afternoon:

    15:30Z, 16:00Z  jobs_seen=667  (steady state, clean runs)
    16:30Z–17:30Z   jobs_seen=332  guard_reason='partial_scrape'
    18:00Z          jobs_seen=173  (guard auto-released, ran unguarded)
    18:30Z–22:00Z   jobs_seen=39   guard_reason='empty_scrape'
    22:30Z, 23:00Z  jobs_seen=0    guard_reason='empty_scrape'

The safety guard did its job: it blocked every write, so all 667 OPEN rows
survived intact (120 CLOSED rows for this company all pre-date the drain, max
``closed_on`` 2026-11-13T03:30:24Z — the guard destroyed nothing). But
``empty_scrape`` does not auto-release (``count_consecutive_partial_skips``
counts ``partial_scrape`` only), so the company is latched dark until this
migration re-points it.

The destination was confirmed from Shield AI's own careers page, which links
"OPEN ROLES" at ``https://jobs.ashbyhq.com/shield`` in four places, and then
verified against the Ashby posting API: 663 live postings whose titles and
locations are unmistakably Shield AI's (Propulsion / Avionics / Mission Systems
roles across Seattle, Dallas, Arlington, San Diego, Melbourne). 663 live vs 667
frozen is a <1% delta — the strongest corroboration signal available that this
is the same board under a new provider, not a different company.

Note the new token is ``shield``, NOT ``shieldai`` — the Lever slug does not
carry over, and ``shield`` is unused by any other tracked company.

Verified live API results at authoring time (2026-11-13)
----------------------------------------------------------
    OLD  https://api.lever.co/v0/postings/shieldai?mode=json
           -> HTTP 200, 0 postings  (also ?limit=200 and ?skip=0&limit=200: 0)
    NEG  https://api.lever.co/v0/postings/zzq-bogus-13nov2300?mode=json
           -> HTTP 404             (proves the probe discriminates: the Lever
                                    token is still VALID, the board is empty)
    NEW  https://api.ashbyhq.com/posting-api/job-board/shield
           -> HTTP 200, 663 postings, apiVersion 1
    NEG  https://api.ashbyhq.com/posting-api/job-board/zzqbogus13nov2310
           -> HTTP 404             (proves ``shield`` is a real board)
    MISS https://api.ashbyhq.com/posting-api/job-board/shieldai     -> 404
         https://api.ashbyhq.com/posting-api/job-board/shield-ai    -> 404
         https://boards-api.greenhouse.io/v1/boards/shieldai/jobs   -> 404
         https://api.gem.com/job_board/v0/shieldai/job_posts/       -> 404

New-provider ids land under a different ``source_id`` than the stale rows
(composite PK ``(source_id, id)``), so incoming rows can never collide with or
dedupe against the old ones. That is exactly why the stale rows must be closed
here rather than left to age out.

Chain position
--------------
Chains off the current single head ``a1d81f01341f``. Frozen per-ATS seed
migrations are never edited — a provider change is a new event, expressed as a
new migration.

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
shield-ai: 1 ``companies`` row re-pointed (lever/shieldai -> ashby/shield),
667 stale ``lever_api`` OPEN ``job_listings`` rows closed. Both counts from
live read-only ``SELECT count(*)`` at authoring time.

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched: all 157 enabled Ashby companies carry
  ``{}``, which is already shield-ai's value, so Ashby requires none.
- ``closed_on`` uses the FIXED sentinel ``_BACKFILL_CLOSED_ON`` (never
  ``now()``) so ``downgrade()`` re-opens EXACTLY the rows this migration closed.
  The sentinel is deliberately **23:30:00Z rather than the template's default
  midnight**: the template requires a value later than every pre-existing
  ``closed_on`` for the affected company, and this company already has rows
  closed at 2026-11-13T03:30:24Z by real scrapes. Midnight would have violated
  that invariant. Verified 0 existing rows match the chosen sentinel exactly.
- The close-out is triple-scoped (company literal AND old source_id AND
  status='OPEN') so it cannot touch other companies, incoming rows, or
  already-closed rows.
- All operations are idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` ``sourceAts`` moved to ``ashby``) and
the ``changelog.ts`` announcement ship in the same PR.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = 'db5e9603b0e3'
down_revision: Union[str, None] = 'a1d81f01341f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after). old_source_id = '<old_ats>_api'.
REPOINTED = [
    {'id': 'shield-ai', 'old_ats': 'lever', 'old_token': 'shieldai',
     'new_ats': 'ashby', 'new_token': 'shield', 'old_source_id': 'lever_api'},
]
# Companies soft-disabled because the destination is unsupported/gone
# (unity3d precedent: row + history preserved, fully reversible).
DISABLED = [
    # {'id': '...', 'reason': '...'},
]
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Must be later than every pre-existing closed_on
# for the affected companies — verified with a read-only MAX(closed_on) query
# (shield-ai max was 2026-11-13T03:30:24.563Z; 0 rows match this sentinel).
_BACKFILL_CLOSED_ON = '2026-11-13T23:30:00+00:00'


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
