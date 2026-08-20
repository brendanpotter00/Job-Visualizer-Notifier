"""The ``meta`` block of ``GET /api/jobs/search`` — what its three numbers mean.

WHY THIS FILE IS THE DELIVERABLE
--------------------------------
``meta`` is the only part of this endpoint a caller cannot check for itself. The
``jobs`` array is self-evident — the client holds the rows and can look at them —
but ``filteredTotal`` is an assertion about rows the client has not fetched yet,
and the two recency tiles are assertions about rows the current filter set
deliberately excludes. Every way of getting them wrong produces a number that
still looks like a number:

* ``filteredTotal`` drifting from what the walk actually yields reads as "247
  matches" over a list that ends at 203. Nobody downstream can tell which one
  lied.
* ``countLast24h`` / ``countLast3h`` quietly picking up the active filters would
  make the "Past 24 Hours" tile mean something new — a smaller, plausible number
  that changes as the user types in the keyword box. Those tiles have always
  counted the visible OPEN feed FOR THE COMPANIES THE READER FOLLOWS, and this
  endpoint inherited that meaning rather than redefining it.
* ...and equally, the tiles quietly DROPPING the company scope would make them
  mean something new in the other direction: on the client-side page they replace,
  both came off ``selectAllJobsFromQuery``, which is the enabled-companies
  prefilter and nothing else. A reader following 3 of 133 companies would watch
  those two numbers jump by ~40x for no reason they could see.

So the assertions here never spot-check a count against a hand-tallied constant
alone. The two central invariants are:

    filteredTotal == the number of rows a complete walk under the same filters
                     returns, exactly

    (countLast24h, countLast3h) honour ``company`` and NOTHING else — invariant
                     under category, level, keywords, locations, ``since`` and
                     ``status`` — varying otherwise only with the corpus's own
                     visibility rules (OPEN, company not deactivated) and the clock

Each dimension case seeds a decoy that the filter must exclude, so a predicate
that silently stopped applying to the count query fails here instead of shipping.
"""

from datetime import datetime, timedelta, timezone

import pytest

from scripts.shared.constants import SourceId

from .conftest import (
    _insert_company,
    _insert_job,
    _insert_job_tag,
    _insert_location,
    _link_job_location,
    _make_job,
)

SEARCH_URL = "/api/jobs/search"

# Fixed anchor for the filter-dimension corpus. Deliberately in the past, well
# outside both recency windows, so those tests' numbers cannot be perturbed by
# the wall clock — and so the recency tests below get a corpus of exactly the
# rows they seed.
BASE_TIME = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _ago(**delta) -> str:
    """An ISO instant ``delta`` before *now*, tz-aware UTC.

    The recency tiles are computed by Postgres against ``now()``, so the only
    honest way to place a row on a chosen side of the 24h/3h boundary is to
    compute the timestamp relative to the real clock rather than to a frozen
    anchor.
    """
    return _iso(datetime.now(timezone.utc) - timedelta(**delta))


def _walk(client, params: dict, *, page_size: int) -> tuple[list[str], list[dict | None]]:
    """Drive a complete search walk; return every job id seen and every page's ``meta``.

    Duplicates are preserved on purpose — collapsing them here would hide the bug
    class that makes ``filteredTotal`` disagree with reality in the first place.
    """
    seen: list[str] = []
    metas: list[dict | None] = []
    cursor: str | None = None
    for page_index in range(200):  # hard cap: a non-terminating walk is a failure
        query = {**params, "limit": page_size}
        if cursor is not None:
            query["cursor"] = cursor
        resp = client.get(SEARCH_URL, params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        page = body["jobs"]
        seen.extend(job["id"] for job in page)
        metas.append(body["meta"])

        # The end-of-walk contract, re-checked on every page: a total that agrees
        # with a walk which truncated early is not agreement, it is two bugs.
        if len(page) == page_size:
            assert body["nextCursor"] is not None, (
                f"page {page_index} was full ({len(page)} rows) but carried no "
                "nextCursor — the walk would truncate here"
            )
        else:
            assert body["nextCursor"] is None, (
                f"page {page_index} was short ({len(page)} of {page_size}) but "
                "carried a nextCursor — the walk would not terminate"
            )

        if body["nextCursor"] is None:
            return seen, metas
        cursor = body["nextCursor"]
    pytest.fail("walk did not terminate within 200 pages")


# ---------------------------------------------------------------------------
# The filter-dimension corpus
# ---------------------------------------------------------------------------
#
# Five rows chosen so that EVERY filter dimension has both a match and a decoy
# that differs from it in that dimension alone. Newest first.

JOB_NEWGRAD = "swe-newgrad-austin"
JOB_SENIOR = "swe-senior-austin"
JOB_PM = "pm-mid-nyc"
JOB_UNENRICHED = "chef-unenriched-nyc"
JOB_UNTAGGED = "swe-entry-untagged"

ALL_JOBS = frozenset(
    {JOB_NEWGRAD, JOB_SENIOR, JOB_PM, JOB_UNENRICHED, JOB_UNTAGGED}
)

# The exact instant JOB_PM was first seen — the `since` case below uses it to
# pin the INCLUSIVE bound rather than a comfortably-clear-of-it value.
PM_FIRST_SEEN = BASE_TIME + timedelta(days=2)


def _seed_dimension_corpus(conn) -> None:
    """Seed the five-row mixed corpus every dimension case filters against."""
    austin = _insert_location(
        conn, canonical_name="Austin, TX, US", kind="city",
        city="Austin", region="TX", country="US",
    )
    new_york = _insert_location(
        conn, canonical_name="New York, NY, US", kind="city",
        city="New York", region="NY", country="US",
    )

    _insert_job(conn, _make_job({
        "id": JOB_NEWGRAD, "company": "google", "source_id": SourceId.GOOGLE,
        "title": "New Grad Software Engineer", "location": "Austin, TX",
        "first_seen_at": _iso(BASE_TIME + timedelta(days=4)),
        "enrichment_category": "software_engineering",
        "enrichment_level": "new_grad",
    }))
    _insert_job(conn, _make_job({
        "id": JOB_SENIOR, "company": "google", "source_id": SourceId.GOOGLE,
        "title": "Senior Software Engineer", "location": "Austin, TX",
        "first_seen_at": _iso(BASE_TIME + timedelta(days=3)),
        "enrichment_category": "software_engineering",
        "enrichment_level": "senior",
    }))
    # Raw location NULL on purpose. The exclude-keyword case below depends on it:
    # without the COALESCE guard in the keyword predicate, `NOT (… OR NULL …)` is
    # NULL and this row would vanish from a negative-keyword count.
    _insert_job(conn, _make_job({
        "id": JOB_PM, "company": "apple", "source_id": SourceId.APPLE,
        "title": "Product Manager", "location": None,
        "first_seen_at": _iso(PM_FIRST_SEEN),
        "enrichment_category": "product_manager", "enrichment_level": "mid",
    }))
    # The unenriched decoy: an active category or level filter must HIDE it, which
    # is the one filter behaviour that looks like a bug until you know the contract.
    _insert_job(conn, _make_job({
        "id": JOB_UNENRICHED, "company": "apple", "source_id": SourceId.APPLE,
        "title": "Head Chef", "location": "New York, NY",
        "first_seen_at": _iso(BASE_TIME + timedelta(days=1)),
    }))
    # Carries the Austin raw text but NO normalized tag — the decoy that proves a
    # location filter reads job_locations and not job_listings.location.
    _insert_job(conn, _make_job({
        "id": JOB_UNTAGGED, "company": "stripe", "source_id": SourceId.GREENHOUSE,
        "title": "Software Engineer", "location": "Austin, TX",
        "first_seen_at": _iso(BASE_TIME),
        "enrichment_category": "software_engineering", "enrichment_level": "entry",
    }))

    _link_job_location(conn, JOB_NEWGRAD, austin)
    _link_job_location(conn, JOB_SENIOR, austin)
    _link_job_location(conn, JOB_PM, new_york)
    _link_job_location(conn, JOB_UNENRICHED, new_york)

    # "python" exists on exactly one row, and only as a tag — so the include case
    # cannot pass by accidentally matching a title or a company name.
    _insert_job_tag(conn, SourceId.GOOGLE, JOB_NEWGRAD, "python")
    _insert_job_tag(conn, SourceId.GOOGLE, JOB_SENIOR, "golang")
    _insert_job_tag(conn, SourceId.APPLE, JOB_PM, "roadmap")


def _seed_two_categories(conn, *, wanted: int, decoys: int) -> None:
    """Seed a corpus large enough to need several pages, split by category.

    The decoys differ from the wanted rows in category only, so a count query that
    dropped the category predicate returns ``wanted + decoys`` — a number that is
    still plausible, which is exactly why it needs a test.
    """
    for n in range(wanted):
        _insert_job(conn, _make_job({
            "id": f"want-{n:03d}", "company": "google", "source_id": SourceId.GOOGLE,
            "title": "Software Engineer",
            "first_seen_at": _iso(BASE_TIME + n * timedelta(minutes=7)),
            "enrichment_category": "software_engineering",
            "enrichment_level": "mid",
        }))
    for n in range(decoys):
        _insert_job(conn, _make_job({
            "id": f"decoy-{n:03d}", "company": "google", "source_id": SourceId.GOOGLE,
            "title": "Product Manager",
            "first_seen_at": _iso(BASE_TIME + n * timedelta(minutes=11)),
            "enrichment_category": "product_manager",
            "enrichment_level": "mid",
        }))


# ---------------------------------------------------------------------------
# (1) filteredTotal is a promise about the walk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("params,expected", [
    pytest.param({}, 40, id="unfiltered"),
    pytest.param({"category": "software_engineering"}, 23, id="filtered"),
])
def test_filtered_total_equals_the_length_of_a_full_walk(
    client, db_conn, seed_taxonomy, params, expected
):
    """The count query and the page query must describe the same result set.

    They are separate SQL statements built from a shared WHERE composer, and the
    count one deliberately drops the ``job_freshness`` join the page query carries.
    That divergence is justified (the sidecar is lossless by construction) but it
    is an assumption, and this is the test that holds it: walk the whole thing at a
    page size that guarantees several cursor round trips, and compare.
    """
    _seed_two_categories(db_conn, wanted=23, decoys=17)

    seen, metas = _walk(client, params, page_size=4)

    assert metas[0] is not None
    assert metas[0]["filteredTotal"] == len(seen), (
        "filteredTotal disagrees with what the walk actually returns — one of the "
        "two is lying to the client and neither can tell which"
    )
    assert len(seen) == len(set(seen)), "the walk returned duplicates"
    assert len(seen) == expected


# ---------------------------------------------------------------------------
# (2) filteredTotal respects every dimension
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("params,expected", [
    pytest.param({}, ALL_JOBS, id="no-filters-counts-the-whole-visible-corpus"),
    pytest.param(
        {"category": "software_engineering"},
        frozenset({JOB_NEWGRAD, JOB_SENIOR, JOB_UNTAGGED}),
        id="category-excludes-other-categories-and-unenriched-rows",
    ),
    pytest.param(
        {"level": "entry"},
        frozenset({JOB_NEWGRAD, JOB_UNTAGGED}),
        id="level-entry-expands-to-new-grad",
    ),
    pytest.param(
        {"level": "new_grad"},
        frozenset({JOB_NEWGRAD}),
        id="level-new-grad-stays-exact",
    ),
    pytest.param(
        {"company": "google"},
        frozenset({JOB_NEWGRAD, JOB_SENIOR}),
        id="company",
    ),
    pytest.param(
        {"company": ["google", "stripe"]},
        frozenset({JOB_NEWGRAD, JOB_SENIOR, JOB_UNTAGGED}),
        id="company-values-or-together",
    ),
    pytest.param(
        {"since": _iso(PM_FIRST_SEEN)},
        frozenset({JOB_NEWGRAD, JOB_SENIOR, JOB_PM}),
        id="since-is-inclusive-of-the-boundary-instant",
    ),
    pytest.param(
        {"include": "python"},
        frozenset({JOB_NEWGRAD}),
        id="include-keyword-reaches-the-tags",
    ),
    pytest.param(
        {"exclude": "chef"},
        frozenset({JOB_NEWGRAD, JOB_SENIOR, JOB_PM, JOB_UNTAGGED}),
        id="exclude-keyword-keeps-rows-with-a-null-raw-location",
    ),
    pytest.param(
        {"location": "Austin, TX, US"},
        frozenset({JOB_NEWGRAD, JOB_SENIOR}),
        id="location-needs-a-normalized-tag-not-matching-raw-text",
    ),
    pytest.param(
        {"category": "software_engineering", "company": "google"},
        frozenset({JOB_NEWGRAD, JOB_SENIOR}),
        id="dimensions-and-together",
    ),
    pytest.param(
        {"category": "growth"},
        frozenset(),
        id="a-well-formed-slug-that-matches-nothing-counts-zero",
    ),
])
def test_filtered_total_counts_exactly_the_rows_the_page_returns(
    client, db_conn, seed_taxonomy, params, expected
):
    """Every filter dimension must reach the count query, not just the page query.

    A dimension applied to one and not the other is the failure this parametrization
    exists for, and it is silent in both directions: too high and the UI promises
    rows that do not exist, too low and it under-reports a list the user can
    already see. Each case's corpus contains at least one decoy the filter must
    drop, so a predicate that stopped applying changes the number rather than
    leaving it coincidentally right.
    """
    _seed_dimension_corpus(db_conn)

    resp = client.get(SEARCH_URL, params={**params, "limit": 500})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert {job["id"] for job in body["jobs"]} == set(expected)
    assert body["meta"]["filteredTotal"] == len(expected)
    assert body["meta"]["filteredTotal"] == len(body["jobs"])
    assert len(expected) < len(ALL_JOBS) or not params, (
        "this case's filter excludes nothing, so it would pass against a count "
        "query with no WHERE clause at all"
    )


# ---------------------------------------------------------------------------
# (3) filteredTotal is a property of the filters, not of the page
# ---------------------------------------------------------------------------


def test_filtered_total_is_unchanged_by_page_size(client, db_conn, seed_taxonomy):
    """``limit`` bounds the page; it must not bound the total.

    Both numbers come out of the same request, so the tempting implementation
    (count what you just fetched) produces a total that equals the page size on
    every page — indistinguishable from correct whenever the corpus happens to fit
    in one page, which is every developer's local dataset.
    """
    _seed_two_categories(db_conn, wanted=23, decoys=17)
    params = {"category": "software_engineering"}

    one = client.get(SEARCH_URL, params={**params, "limit": 1}).json()
    five = client.get(SEARCH_URL, params={**params, "limit": 5}).json()
    everything = client.get(SEARCH_URL, params={**params, "limit": 500}).json()

    assert len(one["jobs"]) == 1
    assert len(five["jobs"]) == 5
    assert len(everything["jobs"]) == 23
    # The pages genuinely differ — including whether the walk continues — while
    # the total does not.
    assert one["nextCursor"] is not None
    assert everything["nextCursor"] is None
    assert one["meta"]["filteredTotal"] == 23
    assert five["meta"]["filteredTotal"] == 23
    assert everything["meta"]["filteredTotal"] == 23


# ---------------------------------------------------------------------------
# (4) The recency tiles ignore every active filter except ``company``
# ---------------------------------------------------------------------------


def _seed_recency_corpus(conn) -> None:
    """Three rows inside the 3h window, two more inside 24h, one long expired.

    Company and category vary so the filter cases below can narrow ``filteredTotal``
    to different values. On every dimension EXCEPT ``company`` the tiles must not
    move at all; ``company`` is the one filter they DO honour, and the two tests
    below split along exactly that line.
    """
    for n in range(3):
        _insert_job(conn, _make_job({
            "id": f"fresh-{n}", "company": "google", "source_id": SourceId.GOOGLE,
            "title": "Software Engineer",
            "first_seen_at": _ago(minutes=10 + n),
            "enrichment_category": "software_engineering",
            "enrichment_level": "mid",
        }))
    _insert_job(conn, _make_job({
        "id": "today-google", "company": "google", "source_id": SourceId.GOOGLE,
        "title": "Software Engineer", "first_seen_at": _ago(hours=8),
        "enrichment_category": "software_engineering", "enrichment_level": "mid",
    }))
    _insert_job(conn, _make_job({
        "id": "today-apple", "company": "apple", "source_id": SourceId.APPLE,
        "title": "Product Manager", "first_seen_at": _ago(hours=9),
        "enrichment_category": "product_manager", "enrichment_level": "mid",
    }))
    _insert_job(conn, _make_job({
        "id": "expired", "company": "apple", "source_id": SourceId.APPLE,
        "title": "Software Engineer", "first_seen_at": _ago(days=9),
        "enrichment_category": "software_engineering", "enrichment_level": "mid",
    }))


@pytest.mark.parametrize("params,expected_total", [
    pytest.param({"category": "growth"}, 0, id="a-filter-matching-nothing"),
    pytest.param({"include": "product"}, 1, id="a-keyword-narrowing-to-one-row"),
    pytest.param({"level": "senior"}, 0, id="a-level-nothing-is-labelled-with"),
    # Every row in this corpus has a NULL subcategory array, so an active
    # subcategory filter hides all six — which is exactly the mid-backfill shape
    # and the strongest possible check that the tiles do not follow the filter.
    pytest.param({"subcategory": "backend"}, 0, id="a-subcategory-nothing-carries"),
    pytest.param(
        {"since": _iso(datetime(2099, 1, 1, tzinfo=timezone.utc))}, 0,
        id="a-since-window-in-the-future",
    ),
])
def test_recency_counts_ignore_the_active_filters(
    client, db_conn, seed_taxonomy, params, expected_total
):
    """The two tiles ignore every filter EXCEPT ``company`` (covered separately below).

    This is a product decision inherited from the client-side page, not an
    accident: "Past 24 Hours" answers "how busy is the job market I follow", and a
    number that shrank every time the user typed in the keyword box would answer a
    different question while looking identical. So ``filteredTotal`` moves across
    these cases and the tiles must not move at all.
    """
    _seed_recency_corpus(db_conn)

    unfiltered = client.get(SEARCH_URL, params={"limit": 500}).json()["meta"]
    assert (unfiltered["countLast24h"], unfiltered["countLast3h"]) == (5, 3)
    assert unfiltered["filteredTotal"] == 6

    resp = client.get(SEARCH_URL, params={**params, "limit": 500})
    assert resp.status_code == 200, resp.text
    meta = resp.json()["meta"]

    assert meta["filteredTotal"] == expected_total, (
        "the filter did not actually change the result set, so this case cannot "
        "distinguish filtered counts from unfiltered ones"
    )
    assert meta["countLast24h"] == unfiltered["countLast24h"]
    assert meta["countLast3h"] == unfiltered["countLast3h"]


@pytest.mark.parametrize("company,expected", [
    pytest.param("apple", (2, 1, 0), id="apple-one-row-inside-24h-none-inside-3h"),
    pytest.param("google", (4, 4, 3), id="google-four-inside-24h-three-inside-3h"),
])
def test_the_recency_tiles_are_scoped_to_the_companies_the_reader_follows(
    client, db_conn, seed_taxonomy, company, expected
):
    """``company`` is the ONE filter the tiles honour, and it is not an exception
    the endpoint invented.

    The page this replaced computed both figures from
    ``selectRecentJobsTimeBasedCounts`` → ``selectAllJobsFromQuery`` →
    ``selectEnabledByCompanyId``: the enabled-companies prefilter, applied before
    any other filter existed. The client sends that same enabled set as
    ``?company=`` here, so dropping the scope would silently re-scope the tiles
    from "the boards I follow" to "every board on the site" — ~40x for a reader
    following 3 of 133 companies, with nothing on screen to explain the jump.

    Both cases are asserted because a single company would not distinguish
    "scoped" from "happens to equal the corpus".
    """
    _seed_recency_corpus(db_conn)

    unfiltered = client.get(SEARCH_URL, params={"limit": 500}).json()["meta"]
    assert (unfiltered["countLast24h"], unfiltered["countLast3h"]) == (5, 3)

    meta = client.get(
        SEARCH_URL, params={"company": company, "limit": 500}
    ).json()["meta"]

    assert (
        meta["filteredTotal"],
        meta["countLast24h"],
        meta["countLast3h"],
    ) == expected


@pytest.mark.parametrize("params,expected", [
    pytest.param(
        {"company": "apple", "category": "software_engineering"}, (1, 1, 0),
        id="company-plus-category",
    ),
    pytest.param(
        {"company": "google", "category": "product_manager"}, (0, 4, 3),
        id="company-plus-a-category-it-has-none-of",
    ),
    pytest.param(
        {"company": "google", "level": "mid"}, (4, 4, 3),
        id="company-plus-level",
    ),
    pytest.param(
        {"company": "apple", "include": "product"}, (1, 1, 0),
        id="company-plus-keyword",
    ),
    pytest.param(
        {"company": ["google", "apple"], "category": "software_engineering"},
        (5, 5, 3),
        id="two-companies-plus-category",
    ),
])
def test_company_combined_with_another_dimension_binds_both_predicates_correctly(
    client, db_conn, seed_taxonomy, params, expected
):
    """``company`` AND another filter — the case where the two WHEREs disagree on arity.

    ``get_search_counts`` renders ONE statement out of two independently-composed
    predicates: the filtered total's WHERE (the whole filter set) as a scalar
    subquery, and the recency tiles' WHERE (``company`` only) on the outer scan.
    Their parameter lists are concatenated ``[*filtered_params, *header_params]``
    and bound BY POSITION against the combined statement text. That is only correct
    while the subquery's placeholders really do all precede the outer WHERE's.

    Every other case in this file gives the two clauses the SAME arity — either no
    company (header binds nothing) or company alone (both bind the same one list) —
    so a placeholder that crossed the boundary would land on an identically-shaped
    value and the numbers would still look right. Here they are deliberately
    UNEQUAL (e.g. status + company + category = 3 params against the header's 1,
    and the keyword case expands to more still), so a crossed placeholder either
    raises or produces a visibly wrong triple.

    The expected values are ``(filteredTotal, countLast24h, countLast3h)`` and are
    chosen so ``filteredTotal`` differs from the tiles in every case: a bug that
    applied the tiles' company-only predicate to the total (or the total's full
    predicate to the tiles) cannot pass by coincidence.
    """
    _seed_recency_corpus(db_conn)

    unfiltered = client.get(SEARCH_URL, params={"limit": 500}).json()["meta"]
    assert (unfiltered["countLast24h"], unfiltered["countLast3h"]) == (5, 3), (
        "corpus drifted; the expectations below are computed from it"
    )

    resp = client.get(SEARCH_URL, params={**params, "limit": 500})
    assert resp.status_code == 200, resp.text
    meta = resp.json()["meta"]

    assert (
        meta["filteredTotal"],
        meta["countLast24h"],
        meta["countLast3h"],
    ) == expected

    # …and the total still has to agree with the rows, which is what proves the
    # subquery's own placeholders did not shift among themselves.
    assert len(resp.json()["jobs"]) == expected[0]


# ---------------------------------------------------------------------------
# (5) …but they do respect the corpus's own visibility rules
# ---------------------------------------------------------------------------


def test_recency_counts_exclude_closed_listings(client, db_conn):
    """A job that closed an hour ago is not a job posted in the last hour.

    The tiles' SQL pins ``status = 'OPEN'`` itself rather than inheriting it from
    the request, so this is the test that the pin is there. Both closed rows are
    freshly ``first_seen_at``, which is what makes them tempting to a window
    predicate that only looks at time.
    """
    for n in range(2):
        _insert_job(db_conn, _make_job({
            "id": f"open-{n}", "company": "google", "source_id": SourceId.GOOGLE,
            "first_seen_at": _ago(minutes=20 + n),
        }))
    for n in range(3):
        _insert_job(db_conn, _make_job({
            "id": f"closed-{n}", "company": "google", "source_id": SourceId.GOOGLE,
            "status": "CLOSED", "first_seen_at": _ago(minutes=30 + n),
        }))

    meta = client.get(SEARCH_URL, params={"limit": 500}).json()["meta"]

    assert meta["filteredTotal"] == 2, "status defaults to OPEN"
    assert meta["countLast24h"] == 2
    assert meta["countLast3h"] == 2


def test_recency_counts_stay_open_only_when_the_caller_asks_for_closed(
    client, db_conn
):
    """``status=CLOSED`` retargets ``filteredTotal`` and nothing else.

    The tiles sit next to a list of closed jobs and still read the live feed —
    strange-sounding, but it is the same "the OPEN feed for the companies the
    reader follows" rule as everywhere else, and the alternative (tiles that flip
    meaning with a dropdown) is worse. Pinned so a future refactor that threads
    ``status`` into ``_header_counts_where`` has to argue with a test.
    """
    for n in range(2):
        _insert_job(db_conn, _make_job({
            "id": f"open-{n}", "company": "google", "source_id": SourceId.GOOGLE,
            "first_seen_at": _ago(minutes=20 + n),
        }))
    for n in range(3):
        _insert_job(db_conn, _make_job({
            "id": f"closed-{n}", "company": "google", "source_id": SourceId.GOOGLE,
            "status": "CLOSED", "first_seen_at": _ago(minutes=30 + n),
        }))

    meta = client.get(
        SEARCH_URL, params={"status": "CLOSED", "limit": 500}
    ).json()["meta"]

    assert meta["filteredTotal"] == 3
    assert meta["countLast24h"] == 2
    assert meta["countLast3h"] == 2


def test_recency_counts_exclude_jobs_from_deactivated_companies(client, db_conn):
    """A soft-deactivated company is invisible on every public read path.

    ``companies.enabled = FALSE`` is the retirement switch, and a retired board's
    rows keep their fresh ``first_seen_at`` forever — so a tile that skipped the
    anti-join would keep advertising a company the product no longer shows. The
    enabled company is seeded explicitly too: without it, the anti-join is a no-op
    and the test would pass against a query that never joined ``companies`` at all.
    """
    _insert_company(db_conn, "google", enabled=True)
    _insert_company(db_conn, "retired", enabled=False)
    for n in range(2):
        _insert_job(db_conn, _make_job({
            "id": f"visible-{n}", "company": "google", "source_id": SourceId.GOOGLE,
            "first_seen_at": _ago(minutes=20 + n),
        }))
    for n in range(4):
        _insert_job(db_conn, _make_job({
            "id": f"hidden-{n}", "company": "retired",
            "source_id": SourceId.GREENHOUSE,
            "first_seen_at": _ago(minutes=40 + n),
        }))

    meta = client.get(SEARCH_URL, params={"limit": 500}).json()["meta"]

    assert meta["filteredTotal"] == 2
    assert meta["countLast24h"] == 2
    assert meta["countLast3h"] == 2


# ---------------------------------------------------------------------------
# (6) Where the two windows actually cut
# ---------------------------------------------------------------------------


def test_recency_counts_split_the_corpus_at_the_24h_and_3h_boundaries(
    client, db_conn
):
    """Each row lands on the side of its window that its age says it should.

    Both tiles come from ``FILTER`` clauses over one scan bounded at 24 hours, so
    the 3h number is a subset of the 24h one by construction — and a mis-sized
    interval (hours vs minutes, ``>`` vs ``>=`` at the wrong column) would still
    produce two ordered numbers that look fine. The rows sit one minute either
    side of each edge: close enough that an off-by-an-hour is caught, far enough
    that ordinary clock skew between this process and Postgres cannot flip one.
    """
    ages = {
        "inside-3h": timedelta(hours=2, minutes=59),
        "outside-3h": timedelta(hours=3, minutes=1),
        "inside-24h": timedelta(hours=23, minutes=59),
        "outside-24h": timedelta(hours=24, minutes=1),
        "ancient": timedelta(days=30),
    }
    for job_id, age in ages.items():
        _insert_job(db_conn, _make_job({
            "id": job_id, "company": "google", "source_id": SourceId.GOOGLE,
            "first_seen_at": _iso(datetime.now(timezone.utc) - age),
        }))

    meta = client.get(SEARCH_URL, params={"limit": 500}).json()["meta"]

    # inside-3h, outside-3h and inside-24h are all younger than a day; only
    # inside-3h is younger than three hours.
    assert meta["countLast24h"] == 3
    assert meta["countLast3h"] == 1
    # And the windows belong to the tiles alone — filteredTotal has no recency
    # bound of its own, so the 30-day-old row is still a match.
    assert meta["filteredTotal"] == 5


# ---------------------------------------------------------------------------
# (7) meta belongs to page 1
# ---------------------------------------------------------------------------


def test_meta_is_absent_from_every_page_after_the_first(
    client, db_conn, seed_taxonomy
):
    """``meta`` describes the filter set, so it is computed once and then omitted.

    Two things have to hold together, which is why they are asserted in one walk:
    the counts really are dropped on cursor pages (recomputing them per page is
    pure waste — ``filteredTotal`` alone is a full count over the matching set),
    and their absence is not mistaken for the end of the walk. A client that keyed
    termination off ``meta`` instead of ``nextCursor`` would stop after page 1 and
    silently show a fifth of the results.
    """
    _seed_two_categories(db_conn, wanted=23, decoys=17)
    params = {"category": "software_engineering"}

    seen, metas = _walk(client, params, page_size=5)

    assert len(metas) > 1, "page size 5 over 23 rows must take several pages"
    assert metas[0] is not None
    assert set(metas[0]) == {"filteredTotal", "countLast24h", "countLast3h"}
    assert all(meta is None for meta in metas[1:]), (
        f"meta must be null on cursor pages; got {metas[1:]}"
    )
    # The walk still completed, and page 1's total still described all of it.
    assert len(seen) == 23
    assert metas[0]["filteredTotal"] == len(seen)


def test_meta_is_absent_on_a_cursor_page_even_when_it_is_the_last_one(
    client, db_conn, seed_taxonomy
):
    """The final page is still a cursor page.

    Called out separately because "recompute the counts when the walk ends" is a
    plausible-looking optimization for a UI that wants a fresh total at the bottom
    of the list — and it would put a second, differently-timed set of numbers on
    the wire under the same field name.
    """
    _seed_two_categories(db_conn, wanted=6, decoys=4)

    first = client.get(
        SEARCH_URL, params={"category": "software_engineering", "limit": 5}
    ).json()
    assert first["meta"]["filteredTotal"] == 6
    assert first["nextCursor"] is not None

    last = client.get(SEARCH_URL, params={
        "category": "software_engineering",
        "limit": 5,
        "cursor": first["nextCursor"],
    }).json()

    assert [job["id"] for job in last["jobs"]] == ["want-000"]
    assert last["nextCursor"] is None
    assert last["meta"] is None
