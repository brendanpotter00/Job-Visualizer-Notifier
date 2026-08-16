"""retire poke — job board removed after Cognition acquisition (detected 2026-08-16)

Revision ID: 1d2d6c17acfc
Revises: d8b52c04f6e3
Create Date: 2026-08-16 14:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — a single UPDATE against ``companies``, so
``scripts/tests/integration/test_alembic_parity.py`` and ``db_models.py`` are
untouched.

Why
---
``poke`` (The Interaction Company of California, makers of Poke) hosted its
board at ``ashby/interaction``. That board returned jobs normally until
2026-08-16T07:01Z and has returned HTTP 404 ever since — the scraper has been
in a 404 storm (113 runs / 24h, every one ``jobs_seen = 0``) since then.

The board was not moved, it was decommissioned. Cognition acquired The
Interaction Company of California on 2026-07-24 (TechCrunch: "The company
behind the assistant, The Interaction Company of California, has been acquired
by AI coding startup Cognition in a deal valuing the startup in the 'low nine
figures.'"), and ~3 weeks later the Ashby board object was deleted. Interaction's
own careers page is now a redirect stub to the acquirer:
``poke.com/jobs`` -> 308 -> ``interaction.co/jobs`` -> hard meta-refresh to
``https://cognition.com/careers``.

There is therefore no Poke board to re-point to. Cognition's own Ashby board
(``ashby/cognition``, 200 with 85 jobs) is a *different company entity* — those
are Cognition's corporate reqs, not Poke's 9 roles, so re-pointing ``poke`` at
it would mislabel Cognition's entire req list as Poke jobs. Cognition should be
onboarded as its own company if it is wanted; that is not this migration.

So ``poke`` is soft-deactivated (unity3d precedent, ``a7c31d9e0b46``): the
``companies`` row, its ``job_listings``/``scrape_runs`` history, its
``user_enabled_companies`` rows, its logos and its ``company_profiles.json``
entry are all preserved, and the retirement is reversible by ``downgrade()``.

Verified live API results at authoring time (2026-08-16)
--------------------------------------------------------
    https://api.ashbyhq.com/posting-api/job-board/interaction        -> 404 "Not Found"
    https://jobs.ashbyhq.com/api/non-user-graphql (interaction)      -> {"data":{"jobBoard":null}}
    https://jobs.ashbyhq.com/api/non-user-graphql (base-power, ctrl) -> jobBoard populated
    https://api.ashbyhq.com/posting-api/job-board/applied  (control) -> 200, 274 jobs
    https://api.ashbyhq.com/posting-api/job-board/base-power (ctrl)  -> 200, 172 jobs
    https://poke.com/jobs                                            -> 308 -> interaction.co/jobs
    https://interaction.co/jobs                                      -> 200, meta-refresh to cognition.com/careers
    ashby/{Interaction,poke,pokeapp,interaction-co,interactionco}    -> 404
    greenhouse|lever|gem / {interaction,poke,interactionco,
                            theinteractioncompany,interactioncompany} -> 404 (15 probes)

The two healthy control boards are what rule out an Ashby-wide outage, and the
GraphQL ``jobBoard: null`` is what distinguishes a *deleted* board from one
that merely has the public posting API switched off (a disabled-API board still
returns a non-null ``jobBoard`` there).

Stale rows are deliberately NOT closed
--------------------------------------
Unlike a re-point, a soft-disable leaves ``job_listings`` untouched — exactly
the unity3d precedent. ``poke``'s 9 OPEN ``ashby_api`` rows stay OPEN in the
table and are hidden from every public read by ``_HIDDEN_COMPANY_PREDICATE``
(``src/backend/api/services/database.py``), which anti-joins on
``companies.enabled = FALSE``. That keeps the retirement a single reversible
flag rather than a data rewrite, and it is why this migration needs no
``closed_on`` sentinel.

Expected prod rowcounts on first run (logged, not asserted)
-----------------------------------------------------------
1 ``companies`` row deactivated (``poke``). 9 ``job_listings`` OPEN rows left
in place, hidden by the predicate above. Verified read-only at authoring time.

- ``created_at`` is NOT touched (auto-enroll watermark).
- ``ats`` / ``board_token`` / ``provider_config`` are NOT touched, so the
  retirement records where the board used to live and ``downgrade()`` restores
  a working configuration if the board ever returns.
- The operation is idempotent and safe to re-run.

The frontend counterpart (``companies.ts`` entry + ``COMPANY_IDS`` member
removed) and the ``changelog.ts`` announcement ship in the same PR.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = '1d2d6c17acfc'
down_revision: Union[str, None] = 'd8b52c04f6e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Companies soft-disabled because the board is gone and the destination is not
# a board for this company (unity3d precedent: row + history preserved, fully
# reversible).
DISABLED = [
    {
        'id': 'poke',
        'reason': (
            'ashby/interaction deleted after the Cognition acquisition; '
            'careers page redirects to cognition.com/careers'
        ),
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    # Rowcount is logged, not asserted: a no-op is legitimate (fresh DB or
    # re-run), but a SILENT no-op is how a drifted id ships as "retired" while
    # the worker keeps 404-storming the dead board — so it reports what it did.
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
    # Exact inverse. ats/board_token were never touched, so re-enabling restores
    # the pre-migration configuration verbatim.
    bind = op.get_bind()
    for row in DISABLED:
        bind.execute(
            sa.text("UPDATE companies SET enabled = TRUE WHERE id = :id"),
            {'id': row['id']},
        )
