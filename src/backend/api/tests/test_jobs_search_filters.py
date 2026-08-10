"""Filter semantics of ``GET /api/jobs/search`` — every dimension, and their AND.

WHAT INVARIANT THIS FILE PROTECTS
---------------------------------
This endpoint exists to move the Recent Jobs page's filtering out of JavaScript
and into SQL (see ``services/job_search.py`` and
``docs/incidents/2026-08-10-recent-jobs-empty-filter-deadlock.md``). A move like
that is only safe if the SQL means *exactly* what the client matcher meant. If it
means something slightly different, nothing breaks loudly: the user sees a list
that is plausible and quietly wrong — a job that should have matched simply is
not there, and there is no error, no empty state, no signal of any kind.

So the assertions here are about MEANING, not about mechanics:

* every dimension is exercised against a corpus that contains a decoy the filter
  must reject, so a predicate that silently degraded to "match everything" fails;
* the null-hiding rules (an active category/level filter hides unenriched rows)
  are pinned as behaviour, because they are the one place where "no filter" and
  "a filter that matches nothing" produce visibly different row counts;
* ``test_server_results_match_client_filter_oracle`` re-implements the frontend
  matcher in pure Python and asserts the endpoint agrees with it row-for-row over
  a fixed corpus and a spread of filter combinations. That test is the deliverable
  of this file — the others explain *why* a given clause is there, but only the
  oracle can catch a divergence nobody thought to write a case for.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from api.services.job_search import expand_levels
from scripts.shared.constants import SourceId

from .conftest import (
    _insert_company,
    _insert_job,
    _insert_job_tag,
    _insert_location,
    _link_job_location,
    _make_job,
)

# Fixed anchor: every timestamp in this module is derived from it, so a failure
# message names a readable instant instead of "now minus something".
BASE_TIME = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _seed_job(conn, job_id: str, *, first_seen_at: datetime | None = None, **overrides) -> dict:
    """Insert one job. ``last_seen_at`` deliberately tracks ``first_seen_at`` —
    nothing in this file reads freshness, and letting them drift would only
    obscure failure output."""
    moment = first_seen_at or BASE_TIME
    job = _make_job({
        "id": job_id,
        "first_seen_at": _iso(moment),
        "last_seen_at": _iso(moment),
        **overrides,
    })
    _insert_job(conn, job)
    return job


def _search(client, **params) -> dict:
    """GET the endpoint, assert it answered, and hand back the envelope."""
    query = {k: v for k, v in params.items() if v is not None}
    resp = client.get("/api/jobs/search", params=query)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(body: dict) -> set[str]:
    return {job["id"] for job in body["jobs"]}


# ---------------------------------------------------------------------------
# (1) category
# ---------------------------------------------------------------------------


def test_category_filter_returns_only_jobs_carrying_that_category(client, db_conn, seed_taxonomy):
    """The decoy carries a *different* category rather than no category, so a
    predicate that had degraded to "has any category" would still fail here."""
    _seed_job(db_conn, "wanted", enrichment_category="software_engineering")
    _seed_job(db_conn, "other-category", enrichment_category="data_scientist")

    body = _search(client, category="software_engineering")

    assert _ids(body) == {"wanted"}
    assert body["meta"]["filteredTotal"] == 1


def test_unenriched_jobs_are_hidden_once_a_category_filter_is_active(
    client, db_conn, seed_taxonomy
):
    """``enrichment_category = %s`` is NULL — not false — for an unlabelled row,
    so SQL drops it. That is deliberate parity with ``matchesCategory``, and it is
    the majority of the OPEN corpus in production, so it is asserted rather than
    assumed. The unfiltered request is part of the test: it proves the row exists
    and is otherwise visible, so the filtered result is hiding it, not missing it.
    """
    _seed_job(db_conn, "labelled", enrichment_category="software_engineering")
    _seed_job(db_conn, "unenriched")  # enrichment_category stays NULL

    assert _ids(_search(client)) == {"labelled", "unenriched"}

    body = _search(client, category="software_engineering")
    assert _ids(body) == {"labelled"}
    assert body["meta"]["filteredTotal"] == 1


def test_multiple_categories_or_together(client, db_conn, seed_taxonomy):
    """Values within a dimension OR. The third row is the decoy: an AND-composed
    multi-select would return nothing, and a dropped predicate would return all
    three."""
    _seed_job(db_conn, "swe", enrichment_category="software_engineering")
    _seed_job(db_conn, "ds", enrichment_category="data_scientist")
    _seed_job(db_conn, "pm", enrichment_category="product_manager")

    body = _search(client, category=["software_engineering", "data_scientist"])

    assert _ids(body) == {"swe", "ds"}
    assert body["meta"]["filteredTotal"] == 2


def test_an_unknown_but_well_formed_category_matches_nothing_without_erroring(
    client, db_conn, seed_taxonomy
):
    """A slug the taxonomy has never heard of is an empty result, not a 400/422 —
    the same thing an unknown value does client-side. Rejecting it would turn a
    stale bookmark into a broken page instead of an empty one."""
    _seed_job(db_conn, "swe", enrichment_category="software_engineering")

    body = _search(client, category="quantum_alchemy")

    assert _ids(body) == set()
    assert body["meta"]["filteredTotal"] == 0


# ---------------------------------------------------------------------------
# (2) level — the new_grad ⊂ entry hierarchy
# ---------------------------------------------------------------------------


def test_entry_level_filter_also_surfaces_new_grad_jobs(client, db_conn, seed_taxonomy):
    """The load-bearing half of the hierarchy: new-grad roles ARE entry-level
    roles, so a user filtering "Entry" who did not see them would conclude the
    tool has no new-grad jobs. ``mid`` is seeded as the decoy that must stay out.
    """
    _seed_job(db_conn, "entry-job", enrichment_level="entry")
    _seed_job(db_conn, "new-grad-job", enrichment_level="new_grad")
    _seed_job(db_conn, "mid-job", enrichment_level="mid")

    body = _search(client, level="entry")

    assert _ids(body) == {"entry-job", "new-grad-job"}
    assert body["meta"]["filteredTotal"] == 2


def test_new_grad_filter_does_not_widen_back_to_plain_entry_jobs(
    client, db_conn, seed_taxonomy
):
    """The expansion is one-directional. Someone filtering "New Grad" is asking a
    narrower question than "Entry"; answering it with every entry-level role would
    make the two options indistinguishable."""
    _seed_job(db_conn, "entry-job", enrichment_level="entry")
    _seed_job(db_conn, "new-grad-job", enrichment_level="new_grad")

    body = _search(client, level="new_grad")

    assert _ids(body) == {"new-grad-job"}
    assert body["meta"]["filteredTotal"] == 1


def test_selecting_entry_and_new_grad_together_returns_each_job_once(
    client, db_conn, seed_taxonomy
):
    """``entry`` expands to ``{entry, new_grad}`` and ``new_grad`` is already in
    the selection, so the expansion has to fold the overlap. The HTTP assertion
    catches duplicated ROWS; the ``expand_levels`` assertion catches the duplicate
    slug itself, which SQL's ``= ANY`` would otherwise swallow silently and carry
    into the query plan."""
    _seed_job(db_conn, "entry-job", enrichment_level="entry")
    _seed_job(db_conn, "new-grad-job", enrichment_level="new_grad")
    _seed_job(db_conn, "senior-job", enrichment_level="senior")

    body = _search(client, level=["entry", "new_grad"])

    returned = [job["id"] for job in body["jobs"]]
    assert sorted(returned) == ["entry-job", "new-grad-job"]
    assert len(returned) == len(set(returned)), "a job was returned twice"
    assert expand_levels(["entry", "new_grad", "senior"]) == ["entry", "new_grad", "senior"]


def test_unenriched_jobs_are_hidden_once_a_level_filter_is_active(
    client, db_conn, seed_taxonomy
):
    """Same NULL-hiding rule as category, on its own column and its own code path
    (``= ANY`` over the expansion rather than plain equality), so it needs its own
    coverage rather than an assumption that one implies the other."""
    _seed_job(db_conn, "levelled", enrichment_level="entry")
    _seed_job(db_conn, "unenriched")  # enrichment_level stays NULL

    assert _ids(_search(client)) == {"levelled", "unenriched"}

    body = _search(client, level="entry")
    assert _ids(body) == {"levelled"}
    assert body["meta"]["filteredTotal"] == 1


# ---------------------------------------------------------------------------
# (3) company — the selection, and the global visibility guard behind it
# ---------------------------------------------------------------------------


def test_company_multi_select_ors_together(client, db_conn, seed_taxonomy):
    """Third company is the decoy. Note the two selected companies also differ in
    ``source_id``, so a filter that keyed off the wrong column would show up."""
    _seed_job(db_conn, "g1", company="google", source_id=SourceId.GOOGLE)
    _seed_job(db_conn, "s1", company="stripe", source_id=SourceId.GREENHOUSE)
    _seed_job(db_conn, "a1", company="apple", source_id=SourceId.APPLE)

    body = _search(client, company=["google", "stripe"])

    assert _ids(body) == {"g1", "s1"}
    assert body["meta"]["filteredTotal"] == 2


def test_jobs_of_a_deactivated_company_are_hidden_with_no_company_param_at_all(
    client, db_conn, seed_taxonomy
):
    """``companies.enabled = FALSE`` is this codebase's soft-deactivation switch,
    and this is a PUBLIC read path — a retired company's listings must not come
    back just because the caller asked for everything. The enabled company is
    seeded alongside so a guard that had inverted into "hide every registered
    company" cannot pass."""
    _seed_job(db_conn, "visible", company="google")
    _seed_job(db_conn, "hidden", company="retiredco")
    _insert_company(db_conn, "google", enabled=True)
    _insert_company(db_conn, "retiredco", enabled=False)

    body = _search(client)

    assert _ids(body) == {"visible"}
    assert body["meta"]["filteredTotal"] == 1
    # And asking for it BY NAME does not get you around the guard.
    assert _ids(_search(client, company="retiredco")) == set()


def test_a_company_with_no_companies_row_at_all_stays_visible(
    client, db_conn, seed_taxonomy
):
    """The guard is an ANTI-join precisely so it means "explicitly deactivated"
    rather than "registered". Flipping it to ``company IN (SELECT id FROM
    companies WHERE enabled)`` would read almost the same and would silently
    blank out every legacy/unregistered company value — including, at the time of
    writing, most of the rows the script scrapers write."""
    _seed_job(db_conn, "unregistered", company="mysteryco")
    _seed_job(db_conn, "registered", company="google")
    _insert_company(db_conn, "google", enabled=True)

    body = _search(client)

    assert _ids(body) == {"unregistered", "registered"}
    assert body["meta"]["filteredTotal"] == 2


# ---------------------------------------------------------------------------
# (4) since
# ---------------------------------------------------------------------------


def test_since_is_inclusive_at_the_exact_boundary_instant(client, db_conn, seed_taxonomy):
    """``first_seen_at >= since``. The row sitting exactly ON the bound is IN, the
    row one microsecond earlier is OUT. Pinned at microsecond resolution because
    an off-by-one here is invisible in any realistic dataset — it surfaces once,
    as a single job the user swears was there a second ago."""
    boundary = BASE_TIME + timedelta(hours=3, microseconds=500)
    for label, moment in (
        ("before", boundary - timedelta(microseconds=1)),
        ("exact", boundary),
        ("after", boundary + timedelta(microseconds=1)),
    ):
        _seed_job(db_conn, label, first_seen_at=moment)

    body = _search(client, since=_iso(boundary))

    assert _ids(body) == {"exact", "after"}
    assert body["meta"]["filteredTotal"] == 2


# ---------------------------------------------------------------------------
# (5) the whole filter set at once
# ---------------------------------------------------------------------------


def test_every_dimension_ands_together_on_a_hand_built_corpus(
    client, db_conn, seed_taxonomy
):
    """One row satisfies the entire filter set; every other row satisfies all of
    it EXCEPT one dimension.

    That shape is the point. A corpus of random near-misses would pass against an
    implementation that dropped a predicate entirely, because some *other*
    predicate would still exclude the row. Here each decoy is held out by exactly
    one clause, so deleting any single clause from the WHERE builder makes exactly
    one decoy leak into the result and this test names it.
    """
    austin = _insert_location(db_conn, canonical_name="Austin, TX, US", kind="city",
                              city="Austin", region="TX", country="US")
    berlin = _insert_location(db_conn, canonical_name="Berlin, BE, DE", kind="city",
                              city="Berlin", region="BE", country="DE")

    # Everything the keeper is; each decoy overrides exactly one of these.
    def seed(job_id: str, *, location_id: int | None = austin,
             tag: str | None = "python", **overrides) -> None:
        defaults = {
            "company": "stripe",
            "title": "New Grad Backend Engineer",
            "location": "Austin, TX",
            "enrichment_category": "software_engineering",
            "enrichment_level": "new_grad",
            "first_seen_at": BASE_TIME + timedelta(hours=10),
        }
        defaults.update(overrides)
        _seed_job(db_conn, job_id, **defaults)
        if location_id is not None:
            _link_job_location(db_conn, job_id, location_id)
        if tag is not None:
            _insert_job_tag(db_conn, "google_scraper", job_id, tag)

    seed("keeper")
    seed("wrong-category", enrichment_category="growth")
    seed("null-category", enrichment_category=None)
    seed("wrong-level", enrichment_level="mid")
    seed("null-level", enrichment_level=None)
    seed("wrong-company", company="openai")
    seed("too-old", first_seen_at=BASE_TIME + timedelta(hours=1))
    seed("no-include-term", tag="golang")
    seed("hits-exclude-term", title="New Grad Backend Engineer Intern")
    seed("wrong-location", location_id=berlin)
    seed("no-location-tag", location_id=None)
    seed("closed", status="CLOSED")

    # Baseline: every decoy really is in the table and really is visible, so the
    # assertion below is about the filters and not about a seeding mistake.
    assert len(_search(client)["jobs"]) == 11, "all but the CLOSED row are visible"

    body = _search(
        client,
        status="OPEN",
        category="software_engineering",
        level="entry",                       # must expand to reach the new_grad keeper
        company=["stripe", "google"],
        location="Austin, TX, US",
        include="python",
        exclude="intern",
        since=_iso(BASE_TIME + timedelta(hours=5)),
    )

    assert _ids(body) == {"keeper"}
    assert body["meta"]["filteredTotal"] == 1


# ---------------------------------------------------------------------------
# (6) THE PARITY LOCK
# ---------------------------------------------------------------------------
#
# ``services/job_search.py`` states that its predicates are a clause-for-clause
# port of the frontend's ``filterJobsByFilters``. Below is that matcher, written
# out in Python, and the assertion that the endpoint agrees with it exactly over
# a fixed corpus. It is the only test here that can catch a divergence nobody
# anticipated — the hand-written cases above each check a rule someone already
# knew to write down.


# Mirrors LEVEL_FILTER_EXPANSION (src/frontend/src/constants/enrichment.ts).
# Written as a literal rather than imported from the service under test: an
# oracle that shares the implementation's table cannot detect the table changing.
_ORACLE_LEVEL_EXPANSION: dict[str, tuple[str, ...]] = {"entry": ("entry", "new_grad")}


@dataclass(frozen=True)
class _OracleJob:
    """The fields the client matcher looks at, as the client would see them."""

    id: str
    status: str
    company: str
    title: str
    location: str | None
    first_seen_at: datetime
    category: str | None
    level: str | None
    tags: tuple[str, ...]
    canonical_locations: tuple[str, ...]
    # The client's ``Job.department``, which the transformer reads from
    # ``details.experience_level`` — mirrored into a plain column of the same
    # name, so the server searches it directly.
    experience_level: str | None = None


def _client_matches(job: _OracleJob, filters: dict) -> bool:
    """Pure-Python translation of ``filterJobsByFilters``.

    Deliberately written as a chain of early returns in the same order the
    frontend applies them, so a reader can diff it against the TypeScript by eye.
    The keyword haystack is title + department + raw location + company + tags.
    ``department`` is the client's name for ``details.experience_level``, which is
    mirrored into a plain column, so both tiers search it. ``team`` is omitted
    because no transformer ever populates it. ``company`` is included because the
    server searches it and the client does not — the one remaining deliberate
    divergence, documented at ``_KEYWORD_PREDICATE``.
    """
    if job.status != filters.get("status", "OPEN"):
        return False

    categories = filters.get("category")
    if categories and (job.category is None or job.category not in categories):
        return False

    levels = filters.get("level")
    if levels:
        if job.level is None:
            return False
        if not any(
            job.level in _ORACLE_LEVEL_EXPANSION.get(level, (level,)) for level in levels
        ):
            return False

    companies = filters.get("company")
    if companies and job.company not in companies:
        return False

    since = filters.get("since")
    if since is not None and job.first_seen_at < since:
        return False

    locations = filters.get("location")
    if locations and not any(name in job.canonical_locations for name in locations):
        return False

    haystack = [
        job.title.lower(),
        (job.experience_level or "").lower(),
        (job.location or "").lower(),
        job.company.lower(),
        *(tag.lower() for tag in job.tags),
    ]

    include = filters.get("include")
    if include and not any(
        term.lower() in field for term in include for field in haystack
    ):
        return False

    exclude = filters.get("exclude")
    if exclude and any(term.lower() in field for term in exclude for field in haystack):
        return False

    return True


# The corpus. Every attribute cycles on its own modulus so the combinations are
# spread rather than correlated, and every value is a literal — a randomized
# corpus would make a failure unreproducible, which on a parity test is fatal:
# the whole value of the assertion is being able to read the row that diverged.
_ORACLE_COMPANIES = ("google", "apple", "stripe", "openai")
_ORACLE_CATEGORIES = (
    None, "software_engineering", "data_scientist", "product_manager", "growth",
)
_ORACLE_LEVELS = (None, "entry", "new_grad", "mid", "senior", "intern")
_ORACLE_TITLES = (
    "Backend Software Engineer",
    "Senior Frontend Engineer",
    "Data Scientist, Search",
    "Product Manager - Payments",
    "Engineering Manager",
    "Software Engineer Intern",
    "Staff Machine Learning Engineer",
)
_ORACLE_RAW_LOCATIONS = ("Austin, TX", None, "Remote - United States")
_ORACLE_TAG_POOLS = (("python",), ("golang", "kubernetes"), (), ("react", "python"))
# Index 3 is "no normalized location at all" — a job the location filter must
# never match, and the case the frontend's ``matchesLocation`` returns false on.
_ORACLE_LOCATION_NAMES = ("Austin, TX, US", "Berlin, BE, DE", "Remote (US)", None)
_ORACLE_LOCATION_ROWS = (
    {"canonical_name": "Austin, TX, US", "kind": "city",
     "city": "Austin", "region": "TX", "country": "US"},
    {"canonical_name": "Berlin, BE, DE", "kind": "city",
     "city": "Berlin", "region": "BE", "country": "DE"},
    {"canonical_name": "Remote (US)", "kind": "remote", "remote_scope": "US"},
)
_ORACLE_SIZE = 40


def _seed_oracle_corpus(conn) -> list[_OracleJob]:
    """Seed the shared corpus and return it in the client matcher's own terms."""
    location_ids = {
        row["canonical_name"]: _insert_location(conn, **row)
        for row in _ORACLE_LOCATION_ROWS
    }

    corpus: list[_OracleJob] = []
    for n in range(_ORACLE_SIZE):
        job_id = f"corpus-{n:02d}"
        source_id = SourceId.GOOGLE if n % 2 == 0 else SourceId.GREENHOUSE
        company = _ORACLE_COMPANIES[n % 4]
        category = _ORACLE_CATEGORIES[n % 5]
        level = _ORACLE_LEVELS[n % 6]
        title = _ORACLE_TITLES[n % 7]
        raw_location = _ORACLE_RAW_LOCATIONS[n % 3]
        tags = _ORACLE_TAG_POOLS[(n // 2) % 4]
        canonical = _ORACLE_LOCATION_NAMES[(n // 3) % 4]
        # A handful of CLOSED rows, so the endpoint's OPEN default is doing work
        # in every single combination below rather than only in the one that
        # names `status` explicitly.
        status = "CLOSED" if n % 11 == 5 else "OPEN"
        first_seen = BASE_TIME + timedelta(hours=n)

        _seed_job(
            conn, job_id,
            source_id=source_id,
            company=company,
            title=title,
            location=raw_location,
            status=status,
            first_seen_at=first_seen,
            enrichment_category=category,
            enrichment_level=level,
        )
        for tag in tags:
            _insert_job_tag(conn, source_id, job_id, tag)
        if canonical is not None:
            _link_job_location(conn, job_id, location_ids[canonical])

        corpus.append(_OracleJob(
            id=job_id,
            status=status,
            company=company,
            title=title,
            location=raw_location,
            first_seen_at=first_seen,
            category=category,
            level=level,
            tags=tags,
            canonical_locations=() if canonical is None else (canonical,),
        ))
    return corpus


# Filter sets walked by the parity test. Chosen to hit each dimension alone, the
# two hierarchy rules, and several intersections — including combinations whose
# answer is a handful of rows, where an off-by-one predicate is most likely to
# hide.
_ORACLE_FILTER_SETS: list[dict] = [
    {},
    {"category": ["software_engineering"]},
    {"category": ["software_engineering", "growth"]},
    {"level": ["entry"]},                       # must reach new_grad rows
    {"level": ["new_grad"]},                    # must NOT reach entry rows
    {"level": ["entry", "senior"]},
    {"company": ["google", "stripe"]},
    {"since": BASE_TIME + timedelta(hours=20)},
    {"include": ["engineer"]},
    {"include": ["python", "manager"]},
    # A term that appears ONLY in the company column. The server searches company
    # and the frontend does not (the one keyword divergence documented at
    # ``_KEYWORD_PREDICATE``), so this pins the divergence the oracle was written
    # to accept — drop ``company`` from either haystack and these two disagree.
    {"include": ["stripe"]},
    {"exclude": ["google"]},
    # "remote" lives only in the RAW location column, so this set is what keeps
    # ``location`` in the haystack — every other keyword set would still pass
    # without it.
    {"include": ["remote"]},
    {"exclude": ["intern"]},
    # Multi-term exclude: a job is dropped if ANY term hits. With a single term
    # "any" and "all" are the same function, so the multi-term case is the only
    # one that pins which of the two the server implements.
    {"exclude": ["intern", "scientist"]},
    {"include": ["engineer"], "exclude": ["senior"]},
    {"location": ["Austin, TX, US"]},
    {"location": ["Austin, TX, US", "Remote (US)"]},
    {"status": "CLOSED"},
    {"category": ["software_engineering"], "level": ["entry"]},
    {"company": ["google", "apple"], "since": BASE_TIME + timedelta(hours=8),
     "include": ["engineer"]},
    {"category": ["software_engineering", "data_scientist"], "level": ["entry", "mid"],
     "company": ["google", "stripe", "openai"], "location": ["Austin, TX, US"],
     "include": ["engineer", "scientist"], "exclude": ["intern"],
     "since": BASE_TIME + timedelta(hours=2)},
]


def test_server_results_match_client_filter_oracle(client, db_conn, seed_taxonomy):
    """The endpoint returns exactly what the client matcher would have returned.

    This is the migration's actual contract. Every other test in this file states
    a rule someone already knew; this one is the only assertion that survives
    *not* knowing — it re-derives the answer independently for every filter set
    in ``_ORACLE_FILTER_SETS`` and compares the id sets element for element.

    ``filteredTotal`` is checked against the same oracle on every combination, so
    the separate count query (which drops the freshness join and is easy to let
    drift from the page query) is held to the same standard as the rows.
    """
    corpus = _seed_oracle_corpus(db_conn)
    all_ids = {job.id for job in corpus}
    strict_subsets = 0

    for filters in _ORACLE_FILTER_SETS:
        expected = {job.id for job in corpus if _client_matches(job, filters)}

        params = dict(filters)
        if "since" in params:
            params["since"] = _iso(params["since"])
        # A page larger than the corpus, so the comparison is over the whole
        # result set and never accidentally over "the first page of it".
        body = _search(client, limit=500, **params)

        assert _ids(body) == expected, (
            f"server and client matcher disagree for {filters!r}\n"
            f"  server-only: {sorted(_ids(body) - expected)}\n"
            f"  client-only: {sorted(expected - _ids(body))}"
        )
        assert body["nextCursor"] is None, "corpus fits in one page"
        assert body["meta"]["filteredTotal"] == len(expected), (
            f"filteredTotal disagrees with the rows it is counting for {filters!r}"
        )

        if 0 < len(expected) < len(all_ids):
            strict_subsets += 1

    # Guard against the whole test passing vacuously: if the corpus and the filter
    # sets ever drift into "everything matches everything", the comparisons above
    # would still pass while proving nothing.
    assert strict_subsets >= len(_ORACLE_FILTER_SETS) - 2, (
        "nearly every filter set must select a non-empty PROPER subset of the "
        "corpus, or this test is not exercising the filters"
    )
