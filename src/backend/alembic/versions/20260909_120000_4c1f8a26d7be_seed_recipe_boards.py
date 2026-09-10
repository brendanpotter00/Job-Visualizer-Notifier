"""seed the four promoted recipe boards

Revision ID: 4c1f8a26d7be
Revises: 87fe6224b0b5
Create Date: 2026-09-09 00:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Promotes four boards that were previously read as *custom* companies onto
the published fleet, using the deterministic recipe engine rather than four
bespoke Python scrapers:

    id          jobs    oracle              verdict at time of writing
    atlassian     230   none                VERIFIED / history_delta_ok
    github         81   declared_probed     VERIFIED / declared_exact
    dell          470   declared_probed     VERIFIED / declared_exact
    oracle      2,234   declared_probed     UNVERIFIED / count_mismatch

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

ORACLE IS SEEDED KNOWING IT CAN NEVER VERIFY, and that is the honest outcome
rather than an oversight. Its board declares ``TotalJobsCount`` 2,239, exposes
2,237 addressable positions, and serves 2,236; the gap is exactly 3 on every
measured sweep, and one record is unreachable in any bulk window a recipe can
express. ``declared_probed`` compares at tolerance 0, so the verdict is a
permanent ``count_mismatch``: Oracle shows all its jobs every run and closes
none. Relabelling the oracle to ``self_consistent`` or ``none`` WOULD produce a
VERIFIED verdict — i.e. permission for destructive closes — purely by changing a
label on a board we cannot prove we read completely. That is precisely why it was
not done. If Oracle ever fixes its own count, this row starts verifying with no
code change.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts (the four rows in the recipe group)
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


# Python literals, NOT json.dumps output. A recipe carrying a boolean
# (oracle's ``stop_on_empty_page``) renders as a bare ``true`` under
# json.dumps, which is an undefined NAME in Python — it compiles fine and
# then NameErrors on import, i.e. at migration time.
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
        'oracle_kind': 'declared_probed'},
    {   'id': 'oracle',
        'display_name': 'Oracle',
        'script': {   'script_version': 1,
                      'transport': 'http_json',
                      'expected_min_jobs': 500,
                      'base_url': 'https://careers.oracle.com',
                      'steps': [   {   'op': 'fetch',
                                       'method': 'GET',
                                       'url': 'https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder=findReqs;siteNumber=CX_45001,facetsList=LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS,limit=200,offset=0,sortBy=POSTING_DATES_DESC',
                                       'headers': {   'accept': '*/*',
                                                      'accept-language': 'en',
                                                      'origin': 'https://careers.oracle.com'}},
                                   {   'op': 'paginate_offset',
                                       'param': 'offset',
                                       'page_size': 200,
                                       'max_pages': 40,
                                       'stop_on_empty_page': True},
                                   {   'op': 'extract_json_path',
                                       'records_path': 'items.0.requisitionList',
                                       'fields': {   'id': 'Id',
                                                     'title': 'Title',
                                                     'url': 'https://careers.oracle.com/en/sites/jobsearch/job/{Id}',
                                                     'location': 'PrimaryLocation',
                                                     'posted_at': 'PostedDate',
                                                     'description': 'ShortDescriptionStr'}},
                                   {'op': 'parse_date', 'field': 'posted_at', 'mode': 'iso'},
                                   {'op': 'dedupe_key', 'field': 'id'},
                                   {'op': 'assert_unique', 'field': 'id'},
                                   {'op': 'assert_page_advances'}],
                      'oracle': {'kind': 'declared_probed', 'total_path': 'items.0.TotalJobsCount'},
                      'discovered_at': '2026-09-09T00:00:00+00:00',
                      'discovered_by': 'hand/published-seed'},
        'transport': 'http_json',
        'oracle_kind': 'declared_probed'},
    {   'id': 'dell',
        'display_name': 'Dell',
        'script': {   'script_version': 1,
                      'transport': 'http_json',
                      'expected_min_jobs': 100,
                      'base_url': 'https://enterpriseplatform.dell.com',
                      'steps': [   {   'op': 'fetch',
                                       'method': 'GET',
                                       'url': 'https://enterpriseplatform.dell.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder=findReqs;siteNumber=CX_1001,facetsList=LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS,limit=200,offset=0,sortBy=POSTING_DATES_DESC',
                                       'headers': {   'accept': '*/*',
                                                      'accept-language': 'en',
                                                      'origin': 'https://enterpriseplatform.dell.com'}},
                                   {   'op': 'paginate_offset',
                                       'param': 'offset',
                                       'page_size': 200,
                                       'max_pages': 25},
                                   {   'op': 'extract_json_path',
                                       'records_path': 'items.0.requisitionList',
                                       'fields': {   'id': 'Id',
                                                     'title': 'Title',
                                                     'url': 'https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers/job/{Id}',
                                                     'location': 'PrimaryLocation',
                                                     'posted_at': 'PostedDate',
                                                     'description': 'ShortDescriptionStr'}},
                                   {'op': 'parse_date', 'field': 'posted_at', 'mode': 'iso'},
                                   {'op': 'dedupe_key', 'field': 'id'},
                                   {'op': 'assert_unique', 'field': 'id'},
                                   {'op': 'assert_page_advances'}],
                      'oracle': {'kind': 'declared_probed', 'total_path': 'items.0.TotalJobsCount'},
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


def downgrade() -> None:
    """Undo the seed — INCLUDING the job rows the boards harvested while seeded.

    THE JOB ROWS ARE THE POINT, and leaving them was a real hole rather than
    untidiness. Deleting only the ``companies`` rows strands ~3,000
    ``recipe:<id>`` ``job_listings`` with no company row. They drop out of
    ``GET /api/jobs`` (it INNER JOINs ``companies``), which is what makes it
    quiet — but ``GET /api/jobs/search`` does not join, so a board nobody is
    scraping any more keeps being served as current, with every row still OPEN
    and nothing left that could ever close them. The read path now fails closed
    on this shape too (``services/database._ORPHANED_CUSTOM_PREDICATE`` covers
    the ``recipe:`` prefix), but a downgrade that knowingly creates the state
    the guard exists to survive is the wrong half of the fix.

    ORDER IS ``custom_companies_service.purge_custom_company``'s, not a new one:
    ``job_locations`` (keyed by ``job_listing_id`` alone, no FK, so it must go
    while the listings still exist, and the NOT EXISTS keeps a shared id's tags
    when another source also serves it) -> ``job_tags`` -> ``job_enrichment`` ->
    ``job_listings`` -> the per-company operational rows -> ``companies``.
    ``job_freshness`` is absent because it CASCADEs off ``job_listings``.

    NEVER-WRONG-CLOSE: every statement is a DELETE. Nothing sets
    ``status='CLOSED'``, nothing writes ``closed_on``, nothing touches
    ``consecutive_misses``. Removing a board's history is not deciding that its
    jobs went away.

    One transaction — Alembic's — so a failure half way strands nothing.
    """
    ids = tuple(row['id'] for row in SEED_ROWS)
    source_ids = tuple('recipe:' + row['id'] for row in SEED_ROWS)
    bind = op.get_bind()

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
    # Scripts before the company: company_scripts has no FK, but dropping the script
    # first keeps the row from ever being selected mid-downgrade.
    _run("DELETE FROM company_scripts WHERE company_id IN :ids", ids=ids)
    _run("DELETE FROM companies WHERE id IN :ids", ids=ids)
