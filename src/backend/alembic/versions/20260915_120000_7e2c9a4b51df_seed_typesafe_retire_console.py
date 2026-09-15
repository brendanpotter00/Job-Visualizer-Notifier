"""seed typesafe-ai and retire console (acquired by Palo Alto Networks)

Revision ID: 7e2c9a4b51df
Revises: 452534ffefb8
Create Date: 2026-09-15 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — INSERT + UPDATE against ``companies`` only.

Two unrelated operations batched because they ship in one PR:

1. SEED ``typesafe-ai`` (TypeSafe) — an AI lab building "intelligence beyond
   chat", team out of OpenAI, Google Brain and Meta/FAIR. Ashby board
   ``typesafe-ai``, verified live 2026-09-15: HTTP 200, 5 jobs, all listed, real
   ISO ``publishedAt`` on 5 of 5, all San Francisco.

   The id carries the ``-ai`` suffix because ``typesafe`` alone is ambiguous:
   Typesafe was the FORMER NAME OF LIGHTBEND, the Scala/Akka company, which is a
   different and much older business. The bare token also 404s
   (``typesafe`` and ``typesafeai`` both), so ``typesafe-ai`` is the only live
   slug as well as the unambiguous one.

2. RETIRE ``console`` — acquired by Palo Alto Networks, board emptied.

WHY CONSOLE IS SOFT-DISABLED RATHER THAN DELETED, and why its OPEN rows are
left alone: this is the unity3d/poke precedent (``a7c31d9e0b46``,
``1d2d6c17acfc``). ``enabled = FALSE`` drops the company from every fan-out
(``list_enabled_companies`` filters on it) AND hides its jobs from every public
read via ``_HIDDEN_COMPANY_PREDICATE`` (``services/database.py``), which
anti-joins on ``companies.enabled = FALSE``. ``ats`` / ``board_token`` /
``provider_config`` / ``created_at`` are NOT touched, so the row records where
the board used to live and ``downgrade()`` restores a working configuration
verbatim if it ever returns. One reversible flag, not a data rewrite.

THIS ALSO RESOLVES A FROZEN-ROW PROBLEM, which is the real reason it matters.
Console's scraper latched on ``empty_scrape`` on 2026-09-11 and, because
``resolve_safety_guard``'s bounded auto-release counts ``partial_scrape`` ONLY
(``incremental.py:count_consecutive_partial_skips``), it could never self-clear:
15 OPEN rows were frozen — never refreshed, never closed — for as long as the
company stayed enabled. Disabling hides them without a destructive close-out.

The zero was real, not a truncation. Verified 2026-09-11 and re-verified
2026-09-15: the Ashby posting API returns ``{"jobs": [], "apiVersion": "1"}``,
the embed GraphQL returns 0 postings, and a posting fetched BY ID returns
``null``. console.com/careers still showed 17 roles at the time, but that page
is a Framer site with 17 HAND-WRITTEN ``jobs.ashbyhq.com/console/<uuid>`` links
— a stale marketing page, not a live board. (Those links answer HTTP 200
because ``jobs.ashbyhq.com`` is a JS shell that 200s for any path; only the API
distinguishes a live posting from a dead one. The health-watch skill was
corrected in #316 to probe the API rather than read the page.)

Expected prod rowcounts on first run (logged, not asserted):
  - 1 ``companies`` row inserted (``typesafe-ai``)
  - 1 ``companies`` row deactivated (``console``)
  - 0 ``job_listings`` rows touched — console's 15 OPEN rows stay in place,
    hidden by the predicate above.

Frontend counterparts ship in the same PR: ``typesafe-ai`` added to
``companies.ts`` + ``COMPANY_IDS``; ``console`` removed from both (the
soft-disable convention — the DB row survives, the frontend entry does not).
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


revision: str = '7e2c9a4b51df'
down_revision: Union[str, None] = '452534ffefb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {
        'id': 'typesafe-ai',
        'display_name': 'TypeSafe',
        'ats': 'ashby',
        'board_token': 'typesafe-ai',
    },
]

DISABLED = [
    {
        'id': 'console',
        'reason': (
            'acquired by Palo Alto Networks; ashby/console still resolves but '
            'serves zero postings (posting API, embed GraphQL and by-id fetch '
            'all confirm empty)'
        ),
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, created_at) "
        "VALUES (:id, :display_name, :ats, :board_token, TRUE, now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        res = bind.execute(insert_sql, row)
        logger.info("seed: %s inserted (%d row)", row['id'], res.rowcount)

    # Rowcount logged, not asserted: a no-op is legitimate (fresh DB or re-run),
    # but a SILENT no-op is how a drifted id ships as "retired" while the worker
    # keeps hitting a dead board every half hour.
    for row in DISABLED:
        res = bind.execute(
            sa.text("UPDATE companies SET enabled = FALSE WHERE id = :id"),
            {'id': row['id']},
        )
        if res.rowcount == 0:
            logger.warning(
                "deactivate: no companies row matched id=%s — still enabled",
                row['id'],
            )
        else:
            logger.info("deactivate: %s enabled=FALSE (%s)", row['id'], row['reason'])


def downgrade() -> None:
    bind = op.get_bind()
    # Exact inverse. console's ats/board_token were never touched, so re-enabling
    # restores the pre-migration configuration verbatim.
    for row in DISABLED:
        bind.execute(
            sa.text("UPDATE companies SET enabled = TRUE WHERE id = :id"),
            {'id': row['id']},
        )
    # typesafe-ai is removed by id. Its job_listings are NOT deleted here: this
    # migration never created them, a later harvest did, and a downgrade that
    # reaches into another process's rows is how a rollback becomes an incident.
    bind.execute(
        sa.text("DELETE FROM companies WHERE id = :id AND ats = 'ashby'"),
        {'id': SEED_ROWS[0]['id']},
    )
