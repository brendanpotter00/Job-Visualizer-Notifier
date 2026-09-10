"""seed the two promoted recipe boards

Revision ID: 4c1f8a26d7be
Revises: 87fe6224b0b5
Create Date: 2026-09-09 00:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Promotes two boards that were previously read as *custom* companies onto
the published fleet, using the deterministic recipe engine rather than two
bespoke Python scrapers:

    id          jobs    oracle              verdict at time of writing
    atlassian     230   none                VERIFIED / history_delta_ok
    github         81   declared_probed     VERIFIED / declared_exact

Dell and Oracle were authored and proved alongside these two, then cut before
merge. Dell (470 jobs, exact declared match) is simply not a company this product
wants to track. Oracle is the more interesting cut and worth recording: its board
declares ``TotalJobsCount`` 2,239, exposes 2,237 addressable positions and serves
2,236. ``declared_probed`` compares at tolerance 0, so that gap is a PERMANENT
``count_mismatch`` — Oracle would have shown every job it had and closed none of
them, every night, forever. A board that can never VERIFY can never close, and a
company whose filled roles never leave the chart is worse than a company we do
not carry. Neither recipe is in the tree; re-adding either later is a fixture
plus a row in this list, not new engine work.

Each company needs BOTH halves and neither is useful alone:

* the ``companies`` row is what ``enqueue_recipe_fan_out`` selects on
  (``ats='recipe' AND enabled AND visibility='public'``), and
* the ``company_scripts`` row is the script the leaf task replays — without it
  ``fetch_custom_company`` returns ``company_or_script_missing`` every run.

``visibility`` is left to its server default of ``'public'``: these are curated
boards, not somebody's private add. That is also what keeps them out of
``reap_ownerless_companies`` and ``reconcile_discovering``, both of which are
``visibility='user'``-scoped — a published recipe board has no ``user_companies``
row and must never be reaped for lacking one.

``board_token`` mirrors the id. There is no vendor board behind a recipe company,
but the column is NOT NULL — the same thing the script companies (tiktok, meta,
amazon) do.

THE PRODUCTION ROLLBACK IS NOT ``alembic downgrade``. It is one statement:

    UPDATE companies SET enabled = false WHERE id IN ('atlassian', 'github');

That is the whole rollback and it is not a euphemism for a partial one. It stops
the fan-out — ``enqueue_recipe_fan_out`` reads ``db.list_enabled_companies``,
which filters ``enabled = true AND visibility = 'public'`` — so no board is
harvested again; and ``services/database._HIDDEN_COMPANY_PREDICATE`` (an
anti-join on ``NOT c.enabled``) keeps the rows already harvested out of the public
``/api/jobs`` list and detail reads. Instant, undone by flipping the flag back,
and it destroys nothing.

``downgrade()`` below is for a local or CI database that wants the pre-seed state
back. RUNNING IT AGAINST PRODUCTION REQUIRES A VERIFIED BACKUP FIRST, because it
DELETES the harvested ``job_listings`` for these boards plus every sidecar hanging
off them (``job_freshness`` CASCADEs off the listings). Re-harvesting is the only
recovery and it is not one: a fresh harvest cannot restore ``first_seen_at``,
``closed_on``, or any of the history the trend charts are drawn from.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts (the rows in the recipe group)
Recipes are committed alongside at:
  src/backend/api/tests/fixtures/recipes/published/<id>.json
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4c1f8a26d7be'
down_revision: Union[str, None] = '87fe6224b0b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Python literals, NOT ``json.dumps`` output. A recipe carrying a boolean renders
# as a bare ``true`` under json.dumps, which is an undefined NAME in Python — it
# compiles fine and then NameErrors on import, i.e. at migration time. No recipe
# in the current corpus carries one, which is exactly why the rule has to be
# written down rather than remembered.
SEED_ROWS = [   {   'id': 'atlassian',
        'display_name': 'Atlassian',
        'script': {   'script_version': 1,
                      'transport': 'http_json',
                      'expected_min_jobs': 50,
                      'base_url': 'https://www.atlassian.com',
                      'steps': [   {   'op': 'fetch',
                                       'method': 'GET',
                                       'url': 'https://www.atlassian.com/endpoint/careers/listings',
                                       'headers': {'accept': 'application/json, text/plain, */*'}},
                                   {   'op': 'extract_json_path',
                                       'records_path': '',
                                       'fields': {   'id': 'id',
                                                     'title': 'title',
                                                     'url': 'portalJobPost.portalUrl',
                                                     'location': 'locations',
                                                     'department': 'category',
                                                     'description': 'responsibilities'}},
                                   {'op': 'dedupe_key', 'field': 'id'},
                                   {'op': 'assert_unique', 'field': 'id'}],
                      'oracle': {'kind': 'none'},
                      'discovered_at': '2026-09-09T00:00:00+00:00',
                      'discovered_by': 'hand/published-seed'},
        'transport': 'http_json',
        'oracle_kind': 'none'},
    {   'id': 'github',
        'display_name': 'GitHub',
        'script': {   'script_version': 1,
                      'transport': 'http_json',
                      'expected_min_jobs': 20,
                      'base_url': 'https://www.github.careers',
                      'steps': [   {   'op': 'fetch',
                                       'method': 'GET',
                                       'url': 'https://www.github.careers/api/jobs?page=1&sortBy=relevance&descending=false&internal=false&limit=100',
                                       'headers': {'accept': 'application/json, text/plain, */*'}},
                                   {   'op': 'paginate_page',
                                       'param': 'page',
                                       'page_size': 100,
                                       'start_page': 1,
                                       'max_pages': 20},
                                   {   'op': 'extract_json_path',
                                       'records_path': 'jobs.*.data',
                                       'fields': {   'id': 'req_id',
                                                     'title': 'title',
                                                     'url': 'https://www.github.careers/careers-home/jobs/{req_id}?lang=en-us',
                                                     'location': 'location_name',
                                                     'posted_at': 'posted_date',
                                                     'description': 'description'}},
                                   {'op': 'parse_date', 'field': 'posted_at', 'mode': 'iso'},
                                   {'op': 'dedupe_key', 'field': 'id'},
                                   {'op': 'assert_unique', 'field': 'id'},
                                   {'op': 'assert_page_advances'}],
                      'oracle': {'kind': 'declared_probed', 'total_path': 'totalCount'},
                      'discovered_at': '2026-09-09T00:00:00+00:00',
                      'discovered_by': 'hand/published-seed'},
        'transport': 'http_json',
        'oracle_kind': 'declared_probed'}]


def upgrade() -> None:
    bind = op.get_bind()
    company_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, created_at) "
        "VALUES (:id, :display_name, 'recipe', :id, TRUE, now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    script_sql = sa.text(
        "INSERT INTO company_scripts "
        "(company_id, script, script_version, transport, oracle_kind) "
        "VALUES (:id, CAST(:script AS jsonb), :script_version, :transport, :oracle_kind) "
        "ON CONFLICT (company_id) DO NOTHING"
    )
    import json as _json
    for row in SEED_ROWS:
        bind.execute(company_sql, {'id': row['id'], 'display_name': row['display_name']})
        bind.execute(script_sql, {
            'id': row['id'],
            'script': _json.dumps(row['script']),
            'script_version': row['script']['script_version'],
            'transport': row['transport'],
            'oracle_kind': row['oracle_kind'],
        })


# --------------------------------------------------------------------------
# The ownership test the downgrade is scoped by
# --------------------------------------------------------------------------
# WHY THIS EXISTS. ``upgrade()`` inserts with ``ON CONFLICT (id) DO NOTHING``, and
# the ``companies`` insert and the ``company_scripts`` insert conflict
# INDEPENDENTLY. So on any database where one of these ids is already taken, this
# migration is a partial no-op — and a ``downgrade()`` that deleted by bare id
# would then destroy rows (and a whole harvested corpus) it never created. Every
# delete below is therefore gated.
#
# WHAT THE TEST IS. A ``companies`` row is treated as ours only if it still looks
# exactly like the row ``upgrade()`` writes: ``ats = 'recipe'`` AND
# ``board_token = id`` AND the seeded ``display_name`` AND ``visibility = 'public'``
# — i.e. every column ``upgrade()`` determines. ``company_scripts`` is judged on
# its own separate evidence, full ``script`` JSONB equality with the recipe this
# file carries, because its insert conflicts separately from the company's.
#
# WHAT IT PROVES: nothing outside the exact shape this migration writes can be
# deleted. A user-added recipe board cannot match (those are ``visibility='user'``).
# A vendor-ATS company that happens to own one of these ids cannot match
# (``ats <> 'recipe'``). A row someone re-pointed at a different board cannot match
# (``board_token <> id``). A ``company_scripts`` row holding anyone else's recipe
# cannot match.
#
# WHAT IT DOES NOT PROVE, stated plainly: not that WE wrote the row — only that the
# row is indistinguishable from the one we would have written. If another actor
# created a byte-identical public recipe company under the same id before this
# migration ran, the ``ON CONFLICT`` skipped our insert and this test still passes,
# and the downgrade deletes their row. Distinguishing those two cases needs a
# provenance record this schema does not have, and adding one for a two-row data
# migration is not worth a table.
#
# ``enabled`` is DELIBERATELY ABSENT from the test even though ``upgrade()`` sets
# it TRUE: the documented production rollback is ``SET enabled = false``, so a
# downgrade run after that rollback must still recognise its own rows.
_OWNED_COMPANY_SQL = sa.text(
    "SELECT 1 FROM companies "
    "WHERE id = :id "
    "  AND ats = 'recipe' "
    "  AND board_token = id "
    "  AND display_name = :display_name "
    "  AND visibility = 'public'"
)


def downgrade() -> None:
    """Undo the seed — INCLUDING the job rows the boards harvested while seeded.

    NOT THE PRODUCTION ROLLBACK. See the module docstring: production rolls back
    with ``UPDATE companies SET enabled = false``, and running this against prod
    needs a verified backup first because the job deletes below are unrecoverable.

    THE JOB ROWS ARE THE POINT, and leaving them was a real hole rather than
    untidiness. Deleting only the ``companies`` rows strands the ``recipe:<id>``
    ``job_listings`` with no company row. They drop out of ``GET /api/jobs`` (it
    INNER JOINs ``companies``), which is what makes it quiet — but
    ``GET /api/jobs/search`` does not join, so a board nobody is scraping any more
    keeps being served as current, with every row still OPEN and nothing left that
    could ever close them. The read path now fails closed on this shape too
    (``services/database._ORPHANED_CUSTOM_PREDICATE`` covers the ``recipe:``
    prefix), but a downgrade that knowingly creates the state the guard exists to
    survive is the wrong half of the fix.

    EVERY DELETE IS SCOPED TO ROWS THIS MIGRATION COULD HAVE CREATED — see
    ``_OWNED_COMPANY_SQL`` above for exactly what that test does and does not
    prove. A company whose row this migration skipped (``ON CONFLICT DO NOTHING``)
    keeps its row, its script, and its entire harvested corpus.

    ORDER IS ``custom_companies_service.purge_custom_company``'s, not a new one:
    ``job_locations`` (keyed by ``job_listing_id`` alone, no FK, so it must go
    while the listings still exist, and the NOT EXISTS keeps a shared id's rows
    when another source also serves it — ``job_listings``' PK is the COMPOSITE
    ``(source_id, id)``, so an id really can appear under two sources) ->
    ``job_tags`` -> ``job_enrichment`` -> ``job_listings`` -> the per-company
    operational rows -> ``company_scripts`` -> ``companies``. ``job_freshness`` is
    absent because it CASCADEs off ``job_listings``.

    NEVER-WRONG-CLOSE: every statement is a DELETE. Nothing sets
    ``status='CLOSED'``, nothing writes ``closed_on``, nothing touches
    ``consecutive_misses``. Removing a board's history is not deciding that its
    jobs went away.

    One transaction — Alembic's — so a failure half way strands nothing, and the
    ownership probes below read the same snapshot the deletes write in.
    """
    import json as _json

    bind = op.get_bind()

    # The scripts are judged one at a time on their own evidence, because their
    # insert conflicted independently of the company's.
    for row in SEED_ROWS:
        bind.execute(
            sa.text(
                "DELETE FROM company_scripts "
                "WHERE company_id = :id AND script = CAST(:script AS jsonb)"
            ),
            {'id': row['id'], 'script': _json.dumps(row['script'])},
        )

    owned = [
        row for row in SEED_ROWS
        if bind.execute(
            _OWNED_COMPANY_SQL,
            {'id': row['id'], 'display_name': row['display_name']},
        ).first() is not None
    ]
    if not owned:
        return

    ids = tuple(row['id'] for row in owned)
    source_ids = tuple('recipe:' + row['id'] for row in owned)

    def _run(statement: str, **params: object) -> None:
        text = sa.text(statement)
        for name, value in params.items():
            text = text.bindparams(sa.bindparam(name, value=value, expanding=True))
        bind.execute(text)

    _run(
        """
        DELETE FROM job_locations jl
        WHERE jl.job_listing_id IN (
                SELECT id FROM job_listings WHERE source_id IN :source_ids
            )
          AND NOT EXISTS (
                SELECT 1 FROM job_listings o
                WHERE o.id = jl.job_listing_id
                  AND o.source_id NOT IN :source_ids
            )
        """,
        source_ids=source_ids,
    )
    _run("DELETE FROM job_tags WHERE source_id IN :source_ids", source_ids=source_ids)
    _run(
        "DELETE FROM job_enrichment WHERE source_id IN :source_ids",
        source_ids=source_ids,
    )
    _run(
        "DELETE FROM job_listings WHERE source_id IN :source_ids",
        source_ids=source_ids,
    )

    # Per-company operational state: a leftover scrape_runs row for a company that
    # no longer exists is a false signal to the health watchdog.
    _run("DELETE FROM company_harvests WHERE company_id IN :ids", ids=ids)
    _run("DELETE FROM scrape_runs WHERE company IN :ids", ids=ids)
    # The company last, re-stating the ownership test inline so the delete cannot
    # widen even if the probe above and this statement ever drift apart.
    for row in owned:
        bind.execute(
            sa.text(
                "DELETE FROM companies "
                "WHERE id = :id "
                "  AND ats = 'recipe' "
                "  AND board_token = id "
                "  AND display_name = :display_name "
                "  AND visibility = 'public'"
            ),
            {'id': row['id'], 'display_name': row['display_name']},
        )
