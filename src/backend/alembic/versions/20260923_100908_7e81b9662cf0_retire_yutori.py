"""retire yutori (public job board removed; company stopped hiring publicly)

Revision ID: 7e81b9662cf0
Revises: 593e96381b3e
Create Date: 2026-09-23 10:09:08.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). No schema change — a single UPDATE against ``companies``.

RETIRE ``yutori`` (Yutori). Opened by ``scraper-health-watch`` after Check A2
(silent-zero) caught it: every run from 2026-09-23T07:35Z on returned
``jobs_seen = 0`` with a six-row error storm per tick — the 404-storm signature.

WHY SOFT-DISABLE RATHER THAN DELETE, and why its 3 OPEN rows are left alone:
the unity3d / console precedent (``a7c31d9e0b46``, ``7e2c9a4b51df``).
``enabled = FALSE`` drops the company from every fan-out
(``list_enabled_companies`` filters on it) AND hides its jobs from every public
read via ``_HIDDEN_COMPANY_PREDICATE`` (``services/database.py``), which
anti-joins on ``companies.enabled = FALSE``. ``ats`` / ``board_token`` /
``provider_config`` / ``created_at`` are NOT touched, so the row still records
where the board used to live and ``downgrade()`` restores a working
configuration verbatim if Yutori starts hiring again. One reversible flag, not
a data rewrite.

WHY "GONE" AND NOT "MOVED" — the board was not relocated, it was withdrawn.
Verified live 2026-09-23, each claim probed twice (research subagent, then
independently by the parent before this file was written):

  - ``https://api.ashbyhq.com/posting-api/job-board/yutori`` → HTTP 404,
    9-byte "Not Found".
  - Ashby's own board GraphQL (``jobs.ashbyhq.com/api/non-user-graphql``,
    ``op=ApiJobBoardWithTeams``, ``organizationHostedJobsPageName='yutori'``)
    → HTTP 200 with ``{"data":{"jobBoard":null}}``. The board OBJECT is gone,
    not merely the posting-API view. Control boards probed in the same pass —
    ``ramp`` (151 postings) and ``town`` (18) — return real boards, so the probe
    method is sound and this is not an Ashby-wide outage.
  - ``yutori.com`` is alive and actively maintained (Navigator/N1.5 launches,
    Scouts iOS app, /changelog, /pricing) — this is not a dead company. Its
    ``/company`` page renders ``["$","$L28",null,{"hiring":false}]``, and in
    chunk ``42u5ghzfl0on5.js`` that flag gates the only careers card in the
    entire frontend: ``name:"We're hiring!" … window.open(
    "https://jobs.ashbyhq.com/yutori")``. They switched hiring off; the one
    careers link they have still points at the board they took down.
    ``/careers``, ``/jobs`` and ``/join`` are all HTTP 404.
  - No replacement board on any supported ATS. All four APIs probed across
    ``yutori``, ``yutori-ai``, ``yutoriai``, ``yutori-labs``, ``yutorilabs``,
    ``yutori-inc``, ``yutori-hq``, ``getyutori``, ``scouts`` and more — every
    one 404. Web search for our frozen postings' Ashby UUIDs
    (``966e9705-…``, ``e87ca3e8-…``) returns only the old dead
    ``jobs.ashbyhq.com/yutori/<uuid>`` URLs; no candidate board serves them.
  - Aggregator mirrors (builtinsf, freehire, radical.getro) carry exactly our
    three frozen titles with no new apply URL, and getro's own Yutori page now
    says "This job is no longer accepting applications". Stale mirrors, not a
    new board.

CAVEAT, recorded deliberately: an Ashby board that is UNPUBLISHED (rather than
deleted) also returns ``jobBoard: null``. "Yutori removed its public board" is
certain; "Yutori deleted its Ashby account" is not distinguishable from the
outside. Either way there is nothing fetchable on any ATS this repo supports,
and the fix is the same reversible flag.

Expected prod rowcounts on first run (logged, not asserted):
  - 1 ``companies`` row deactivated (``yutori``)
  - 0 ``job_listings`` rows touched — yutori's 3 OPEN rows stay in place,
    hidden by the predicate above.

Frontend counterpart ships in the same PR: ``yutori`` removed from
``companies.ts`` + ``COMPANY_IDS`` (the soft-disable convention — the DB row
survives, the frontend entry does not).
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")


revision: str = '7e81b9662cf0'
down_revision: Union[str, None] = '593e96381b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DISABLED = [
    {
        'id': 'yutori',
        'reason': (
            'public Ashby board withdrawn — posting API 404s and the board '
            'GraphQL returns jobBoard:null, while yutori.com renders its '
            'careers card behind hiring:false; no replacement board on any '
            'supported ATS'
        ),
    },
]


def upgrade() -> None:
    bind = op.get_bind()

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
    # Exact inverse. yutori's ats/board_token were never touched, so re-enabling
    # restores the pre-migration configuration verbatim.
    for row in DISABLED:
        bind.execute(
            sa.text("UPDATE companies SET enabled = TRUE WHERE id = :id"),
            {'id': row['id']},
        )
