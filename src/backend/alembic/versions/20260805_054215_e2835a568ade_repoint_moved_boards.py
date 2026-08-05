"""repoint fireworksai and thinkingmachines to ashby

Revision ID: e2835a568ade
Revises: 08765ce81d35
Create Date: 2026-08-05 05:42:15.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — UPDATEs against ``companies`` / ``job_listings`` only,
so ``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched. Detected and authored by the ``scraper-health-watch`` skill's
supervised first run (2026-08-05).

Why
---
Fireworks AI and Thinking Machines silently moved their job boards from
Greenhouse to Ashby. JVN kept polling the dead Greenhouse boards:
fireworksai has recorded zero-job runs since 2026-07-31 (~105h dark at
detection, 288/288 errored runs in 24h — the 404 retry-storm signature) and
thinkingmachines since 2026-08-04 (~13h dark). Their frozen OPEN rows were
still being served while never re-verified upstream.

Verified live API results at authoring time (2026-08-05)
--------------------------------------------------------
Greenhouse job-board API (``boards-api.greenhouse.io/v1/boards/<token>/jobs``):

  fireworksai       HTTP 404
  thinkingmachines  HTTP 404

Ashby posting API (``api.ashbyhq.com/posting-api/job-board/<token>``), the
exact endpoint ``api/services/ashby_client.py`` calls:

  fireworks         HTTP 200, 49 jobs (sample: "AI Product Engineer")
  thinkingmachines  HTTP 200, 35 jobs (sample: "Software Engineer, Platform,
                    Tinker" — Tinker is Thinking Machines Lab's product, and
                    thinkingmachines.ai's careers links point at
                    jobs.ashbyhq.com/ThinkingMachines)

Ashby ids are UUID-shaped and land under ``source_id = 'ashby_api'``, while the
stale rows are numeric under ``source_id = 'greenhouse_api'``, so incoming rows
can never collide with (or dedupe against) the old ones on the composite
``(source_id, id)`` primary key. That is exactly why the stale Greenhouse rows
must be closed here rather than left to age out.

Chain position
--------------
Chains off the current single head ``08765ce81d35`` (originally authored
against ``a3c32c2aa4d3``; re-parented 2026-08-05 after ``18fe9c20a8fd`` —
which dropped the legacy ``job_listings`` freshness columns this migration
never touches — and ``08765ce81d35`` landed on main). Frozen per-ATS seed
migrations are never edited — a provider change is a new event, expressed as a
new migration (same rationale as ``a7c31d9e0b46``, the 2026-07-30 repoint).

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
1 ``companies`` row repointed per company; stale ``job_listings`` closed:
fireworksai 48, thinkingmachines 36 (84 total). Counted live on 2026-08-05 via
``SELECT count(*) ... source_id='greenhouse_api' AND status='OPEN'``.

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``provider_config`` is NOT touched: Ashby rows carry ``{}`` and both hold
  ``{}`` in prod.
- ``closed_on`` uses the FIXED sentinel ``_BACKFILL_CLOSED_ON`` (never
  ``now()``) so ``downgrade()`` re-opens EXACTLY the rows this migration
  closed. Both companies' latest pre-existing ``closed_on`` is 2026-07-30, so
  the 2026-08-05 sentinel cannot collide (real closes carry sub-second
  timestamps, never exact midnight).
- The close-out is triple-scoped (company literal AND ``source_id =
  'greenhouse_api'`` AND ``status = 'OPEN'``) so it cannot touch other
  companies, incoming Ashby rows, or already-closed rows.
- All operations are idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` entries moved into the
migrated-to-Ashby block with ``sourceAts: 'ashby'``; ids and ``COMPANY_IDS``
members unchanged) and the ``changelog.ts`` announcement ship in the same PR.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = 'e2835a568ade'
down_revision: Union[str, None] = '08765ce81d35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, ats/token before, ats/token after). old_source_id drives the close-out.
REPOINTED = [
    {'id': 'fireworksai', 'old_ats': 'greenhouse', 'old_token': 'fireworksai',
     'new_ats': 'ashby', 'new_token': 'fireworks',
     'old_source_id': 'greenhouse_api'},
    {'id': 'thinkingmachines', 'old_ats': 'greenhouse',
     'old_token': 'thinkingmachines', 'new_ats': 'ashby',
     'new_token': 'thinkingmachines', 'old_source_id': 'greenhouse_api'},
]
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Later than every pre-existing closed_on for these
# companies (max 2026-07-30), so it cannot collide.
_BACKFILL_CLOSED_ON = '2026-08-05T00:00:00+00:00'


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
    # Expected in prod on first run: 1 row repointed per company, and
    # 48 / 36 rows closed respectively.
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


def downgrade() -> None:
    # Exact inverse, in reverse order. The closed_on sentinel match makes the
    # re-open surgical: rows closed by a real scrape (different timestamp)
    # stay CLOSED.
    bind = op.get_bind()
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
