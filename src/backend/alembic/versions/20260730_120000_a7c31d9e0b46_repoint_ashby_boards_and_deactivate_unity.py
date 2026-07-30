"""repoint applied intuition/fal/merge to ashby and deactivate unity

Revision ID: a7c31d9e0b46
Revises: 5ee285a3c724
Create Date: 2026-07-30 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). No schema change — three ``UPDATE``s against
``companies`` / ``job_listings``, so
``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py``
are untouched.

Why
---
Applied Intuition, fal, and Merge silently moved their job boards from
Greenhouse to Ashby. JVN kept polling the dead Greenhouse boards, so the
site had been serving months-old, already-filled listings for all three.
Unity moved to Workday, which JVN deliberately does not read for them, so
Unity is soft-deactivated instead (``companies.enabled = FALSE``) — the row
and all of its history are preserved and the change is fully reversible.

Verified live API results at authoring time (2026-07-30)
--------------------------------------------------------
Greenhouse job-board API (``boards-api.greenhouse.io/v1/boards/<token>/jobs``):

  appliedintuition  HTTP 404
  fal               HTTP 404
  merge             HTTP 200 with ``jobs: []`` (emptied, not deleted)
  unity3d           HTTP 404

Ashby posting API (``api.ashbyhq.com/posting-api/job-board/<token>``), the
exact endpoint ``api/services/ashby_client.py`` calls:

  applied           HTTP 200, 267 jobs
  fal-ai            HTTP 200,  31 jobs
  merge             HTTP 200,  18 jobs

Ashby ids are UUID-shaped and land under ``source_id = 'ashby_api'``, while
the stale rows are numeric under ``source_id = 'greenhouse_api'``, so the
incoming rows can never collide with (or dedupe against) the old ones on the
composite ``(source_id, id)`` primary key. That is exactly why the stale
Greenhouse rows must be closed here rather than left to age out.

Chain position
--------------
Chains off the current head ``5ee285a3c724`` so the alembic chain keeps a
single head. Lands AFTER the frozen per-ATS seed migrations (greenhouse
``939331c99a23``, ashby ``a17b7c0ffee500``) and after the single-company fal
seed (``f6c3a1d4e5b2``), so the per-ATS row counts asserted in
``api/tests/test_migration_companies.py`` are unaffected — those tests upgrade
only to the seed revisions, never to head, so they still observe the original
counts at the seed point. We do NOT edit the frozen seeds; a provider change
is a new event, expressed as a new migration.

The three operations
--------------------
1. Re-point the three companies: ``ats = 'ashby'`` plus the new board token
   (``appliedintuition -> applied``, ``fal -> fal-ai``, ``merge -> merge``).
   The JVN ``id`` is deliberately unchanged — it is the ``companies`` PK, the
   ``job_listings.company`` foreign value, and the frontend logo key.

2. Close the stale Greenhouse-era rows for those three companies. Expected
   rowcounts in prod: appliedintuition 228, fal 38, merge 21 (287 total).

3. Soft-deactivate Unity (``enabled = FALSE``). Its ``job_listings`` are NOT
   touched — the read-path guard in ``api/services/database.py``
   (``_HIDDEN_COMPANY_PREDICATE``) hides them from the public ``/api/jobs``
   paths, while ``/api/jobs-qa/*`` diagnostics deliberately still see them.

Rationale for what is deliberately NOT touched
----------------------------------------------
- ``created_at`` is NOT touched: it is the auto-enroll watermark. A
  delete+reinsert would look like a brand-new company and force-add these
  three to every auto-enroll user's feed. An in-place ``UPDATE`` does not.
- ``provider_config`` is NOT touched: Ashby rows carry ``{}`` and all three
  already hold ``{}`` in prod, so there is nothing to change.
- ``closed_on`` uses a FIXED sentinel (``_BACKFILL_CLOSED_ON``), not
  ``now()``, so ``downgrade()`` can re-open EXACTLY the rows this migration
  closed and nothing else. The rows already legitimately closed for these
  companies carry ``closed_on`` no later than 2026-07-06, so the sentinel
  cannot collide with them.
- The backfill is triple-scoped (``company`` = one of the three literals AND
  ``source_id = 'greenhouse_api'`` AND ``status = 'OPEN'``), so it cannot
  touch Unity, the incoming Ashby rows, already-CLOSED rows, or any other
  company.
- All three operations are idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` entries re-pointed into the Ashby
block with ``sourceAts: 'ashby'``, Unity's entry + ``COMPANY_IDS`` member
removed) and the changelog announcement ship in the same PR. Unity's logos,
its ``company_profiles.json`` entry, and its ``user_enabled_companies`` rows
are deliberately kept so the retirement is lossless and reversible.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = 'a7c31d9e0b46'
down_revision: Union[str, None] = '5ee285a3c724'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (id, greenhouse board_token before, ashby board_token after)
REPOINTED = [
    {'id': 'appliedintuition', 'old_token': 'appliedintuition', 'new_token': 'applied'},
    {'id': 'fal',              'old_token': 'fal',              'new_token': 'fal-ai'},
    {'id': 'merge',            'old_token': 'merge',            'new_token': 'merge'},
]
UNITY_ID = 'unity3d'
STALE_SOURCE_ID = 'greenhouse_api'
# Fixed sentinel, NOT now(): downgrade() matches on it to re-open exactly the
# rows this migration closed. Later than every pre-existing closed_on for these
# companies (max 2026-07-06), so it cannot collide.
_BACKFILL_CLOSED_ON = '2026-07-30T00:00:00+00:00'


def upgrade() -> None:
    bind = op.get_bind()
    repoint = sa.text(
        "UPDATE companies SET ats = 'ashby', board_token = :new_token WHERE id = :id"
    )
    close_stale = sa.text(
        "UPDATE job_listings SET status = 'CLOSED', "
        "closed_on = CAST(:closed_on AS timestamptz) "
        "WHERE company = :id AND source_id = :source_id AND status = 'OPEN'"
    )
    # Rowcounts are logged, not asserted. A no-op here is a legitimate state
    # (fresh DB with no job_listings, or a re-run), so raising would be wrong.
    # But a SILENT no-op is how a drifted id ships as "migrated" while the
    # boards stay dead, so every statement reports what it actually touched.
    # Expected in prod on first run: 1 row repointed per company, and
    # 228 / 38 / 21 rows closed respectively.
    for row in REPOINTED:
        res = bind.execute(repoint, {'id': row['id'], 'new_token': row['new_token']})
        if res.rowcount == 0:
            logger.warning(
                "repoint: no companies row matched id=%s — board NOT repointed",
                row['id'],
            )
        else:
            logger.info(
                "repoint: %s -> ashby/%s (%d row)",
                row['id'], row['new_token'], res.rowcount,
            )
        closed = bind.execute(
            close_stale,
            {
                'id': row['id'],
                'source_id': STALE_SOURCE_ID,
                'closed_on': _BACKFILL_CLOSED_ON,
            },
        )
        logger.info(
            "backfill: closed %d stale %s rows for %s",
            closed.rowcount, STALE_SOURCE_ID, row['id'],
        )

    # Soft-deactivation only — Unity's job_listings / scrape_runs /
    # user_enabled_companies rows all stay.
    disabled = bind.execute(
        sa.text("UPDATE companies SET enabled = FALSE WHERE id = :id"),
        {'id': UNITY_ID},
    )
    if disabled.rowcount == 0:
        logger.warning(
            "deactivate: no companies row matched id=%s — still enabled", UNITY_ID
        )
    else:
        logger.info("deactivate: %s enabled=FALSE (%d row)", UNITY_ID, disabled.rowcount)


def downgrade() -> None:
    # Exact inverse, in reverse order. The closed_on sentinel match is what
    # makes the re-open surgical: rows closed by a real scrape (different
    # timestamp) stay CLOSED.
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE companies SET enabled = TRUE WHERE id = :id"),
        {'id': UNITY_ID},
    )
    reopen = sa.text(
        "UPDATE job_listings SET status = 'OPEN', closed_on = NULL "
        "WHERE company = :id AND source_id = :source_id AND status = 'CLOSED' "
        "AND closed_on = CAST(:closed_on AS timestamptz)"
    )
    unrepoint = sa.text(
        "UPDATE companies SET ats = 'greenhouse', board_token = :old_token WHERE id = :id"
    )
    for row in REPOINTED:
        bind.execute(
            reopen,
            {
                'id': row['id'],
                'source_id': STALE_SOURCE_ID,
                'closed_on': _BACKFILL_CLOSED_ON,
            },
        )
        bind.execute(unrepoint, {'id': row['id'], 'old_token': row['old_token']})
