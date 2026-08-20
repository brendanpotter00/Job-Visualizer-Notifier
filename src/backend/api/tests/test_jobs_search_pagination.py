"""Paging-correctness tests for the FILTERED keyset walk on ``GET /api/jobs/search``.

WHY THIS FILE IS THE DELIVERABLE
--------------------------------
``/api/jobs`` pages an unfiltered dump and lets the client decide what to keep, so
a paging bug there costs the caller rows it could have re-fetched. This endpoint
pages the *filtered result set*, which changes the stakes twice over:

* the client has no other copy of the corpus — a row this walk skips is a job the
  user is never shown, and nothing downstream can tell that it is missing; and
* "the page came back empty" is now the ONLY termination signal, so a cursor that
  drifts off the filtered ordering does not error, it just stops the feed early or
  loops forever.

Both failures are 200s. So every test here asserts the WALK, not a response:

    the multiset of rows returned across all pages == the matching set, exactly

— no duplicates, no gaps, no non-matching row, right order, and termination.
Every fixture therefore seeds **decoys**: rows interleaved *between* the matches in
the sort order that the filter must exclude. Without them a walk that quietly
dropped the WHERE clause would still return "the right number of rows" on a
uniform corpus and every assertion would pass.

The mutation scenarios are the ones that actually happen here, hourly: a scrape
inserting at the head of the ordering mid-walk, close-detection deleting behind
it, and — unique to this endpoint — the **enricher labelling a row mid-walk**, so a
job that did not match the filter on page 1 does match by page 3.

The final section asserts the *plan* at prod scale. A filtered walk that returns
correct pages by scanning past the 65% of OPEN rows the enricher has not labelled
is indistinguishable from a fast one in every test above, and is the reason
``idx_job_listings_open_category_keyset`` exists.
"""

from datetime import datetime, timedelta, timezone

import pytest
from psycopg2 import sql

from api.pagination import JobCursor, compute_filter_fingerprint, decode_search_cursor
from api.services import database as db_service
from api.services import job_search as search_service
from scripts.shared.constants import SourceId

from .conftest import _insert_job, _make_job

SEARCH_URL = "/api/jobs/search"

# Fixed anchor so every timestamp in this module is deterministic and readable in
# failure output. Deliberately in the past relative to any real "now", so the
# recency tiles in ``meta`` cannot accidentally depend on wall-clock time.
BASE_TIME = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

# The filter every walk in this file runs under, plus a sibling slug used for
# decoys. Both must exist in ``job_categories`` — hence ``seed_taxonomy``.
FILTER_CATEGORY = "software_engineering"
OTHER_CATEGORY = "data_scientist"


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _fingerprint(
    *,
    status: str = "OPEN",
    since: str | None = None,
    category: list[str] | None = None,
    level: list[str] | None = None,
    company: list[str] | None = None,
    location: list[str] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> str:
    """The fingerprint the router computes for a filter set.

    Rebuilt from the same primitive rather than scraped off a response, so a test
    that decodes a cursor is checking the cursor's contents and not merely that
    the server agrees with itself.
    """
    return compute_filter_fingerprint(
        {
            "status": status,
            "since": since,
            "category": category or [],
            "level": level or [],
            "company": company or [],
            "location": location or [],
            "include": include or [],
            "exclude": exclude or [],
        }
    )


def _insert_row(
    conn,
    job_id: str,
    moment: datetime,
    *,
    category: str | None = None,
    source_id: str = SourceId.GOOGLE,
    company: str = "google",
    status: str = "OPEN",
) -> tuple[str, str]:
    """Seed one listing and return its ``(source_id, id)`` keyset identity."""
    _insert_job(
        conn,
        _make_job(
            {
                "id": job_id,
                "company": company,
                "source_id": source_id,
                "status": status,
                "first_seen_at": _iso(moment),
                # Freshness deliberately runs OPPOSITE to first_seen_at: this
                # endpoint must never fall back to the legacy last_seen_at
                # ordering, and if it did the sequence would be visibly reversed
                # rather than coincidentally right.
                "last_seen_at": _iso(BASE_TIME + timedelta(days=365) - (moment - BASE_TIME)),
                "enrichment_category": category,
            }
        ),
    )
    return (source_id, job_id)


def _seed_corpus(
    conn,
    matches: int,
    *,
    start: datetime = BASE_TIME,
    spacing: timedelta = timedelta(minutes=12),
    prefix: str = "m",
) -> list[tuple[str, str]]:
    """Seed ``matches`` rows in :data:`FILTER_CATEGORY`, each followed by two decoys.

    The decoys sit at timestamps strictly BETWEEN consecutive matches, so in the
    DESC ordering every match is separated from the next by a row the filter must
    drop. That placement is the whole point: it means a walk whose cursor boundary
    ignores the filter lands on a decoy and either re-serves or skips a real match,
    instead of coincidentally producing the right sequence on a uniform corpus.

    Returns the matching ``(source_id, id)`` keys in the endpoint's DESC order.
    """
    keys: list[tuple[str, str]] = []
    for n in range(matches):
        moment = start + n * spacing
        keys.append(
            _insert_row(conn, f"{prefix}-{n:04d}", moment, category=FILTER_CATEGORY)
        )
        # A row of a DIFFERENT category — the filter's positive case.
        _insert_row(
            conn, f"{prefix}-other-{n:04d}", moment + spacing / 3, category=OTHER_CATEGORY
        )
        # An UNENRICHED row (NULL category). ``= ANY(...)`` is NULL for these, so
        # an active category filter must hide them; ~65% of OPEN rows in prod look
        # like this, which makes it the decoy most likely to leak.
        _insert_row(conn, f"{prefix}-null-{n:04d}", moment + 2 * spacing / 3)
    keys.reverse()
    return keys


def _walk(
    client,
    *,
    page_size: int,
    params: dict | None = None,
    between_pages=None,
) -> list[tuple[str, str]]:
    """Drive a complete filtered walk and return every ``(sourceId, id)`` served.

    Duplicates are preserved on purpose — de-duplicating here would hide the exact
    bug class these tests exist to catch.

    Two envelope invariants are re-checked on EVERY page rather than once at the
    end, because each is the sole signal for something the client cannot otherwise
    observe: ``nextCursor`` present iff the page came back full (the only
    end-of-walk signal), and ``meta`` present iff this is page 1 (the counts
    describe the filter set, so a cursor page carrying them would mean the server
    is recomputing them per page).

    ``between_pages(page_index)`` runs after each page is fetched — where the
    concurrency tests mutate the table mid-walk.
    """
    base = {"status": "OPEN", **(params or {})}
    seen: list[tuple[str, str]] = []
    cursor: str | None = None
    for page_index in range(200):  # hard cap: a non-terminating walk is a failure
        query = {**base, "limit": page_size}
        if cursor is not None:
            query["cursor"] = cursor
        resp = client.get(SEARCH_URL, params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        page = body["jobs"]
        seen.extend((job["sourceId"], job["id"]) for job in page)

        next_cursor = body["nextCursor"]
        if len(page) == page_size:
            assert next_cursor is not None, (
                f"page {page_index} was full ({len(page)} rows) but carried no "
                "nextCursor — the walk would truncate here"
            )
        else:
            assert next_cursor is None, (
                f"page {page_index} was short ({len(page)} of {page_size}) but "
                "carried a nextCursor — the walk would not terminate"
            )

        if cursor is None:
            assert body["meta"] is not None, "page 1 must carry the header counts"
        else:
            assert body["meta"] is None, (
                f"page {page_index} is a cursor page and must not recompute meta"
            )

        if between_pages is not None:
            between_pages(page_index)

        if next_cursor is None:
            return seen
        cursor = next_cursor
    pytest.fail("walk did not terminate within 200 pages")


def _assert_exactly_once(
    seen: list[tuple[str, str]], expected: list[tuple[str, str]]
) -> None:
    """Every expected row returned exactly once, in order, and nothing else."""
    duplicates = [k for k in set(seen) if seen.count(k) > 1]
    assert not duplicates, f"rows returned more than once: {sorted(duplicates)}"
    missing = [k for k in expected if k not in seen]
    assert not missing, f"rows silently dropped by the walk: {sorted(missing)}"
    unexpected = [k for k in seen if k not in expected]
    assert not unexpected, (
        f"rows the filter should have excluded: {sorted(unexpected)}"
    )
    assert seen == expected, "walk returned the right rows in the wrong order"


# ---------------------------------------------------------------------------
# (1) The filtered walk
# ---------------------------------------------------------------------------


def test_full_walk_under_a_category_filter_returns_every_match_exactly_once(
    client, db_conn, seed_taxonomy
):
    """23 matches / page size 5 — deliberately not a multiple, so the walk must
    terminate on the absent ``nextCursor`` rather than on a row count.

    46 decoys are interleaved between the matches. They are what makes this a real
    test: on a corpus of nothing but matches, a page query that lost its WHERE
    clause would return the same *count* of rows in the same *order* and every
    assertion below would still hold.
    """
    expected = _seed_corpus(db_conn, 23)

    seen = _walk(client, page_size=5, params={"category": FILTER_CATEGORY})

    _assert_exactly_once(seen, expected)
    assert len(seen) == 23


def test_walk_with_page_size_one_covers_every_filtered_row(client, db_conn, seed_taxonomy):
    """Page size 1 maximizes cursor round trips, so an off-by-one in the boundary
    predicate (``<`` vs ``<=``) shows up as a duplicate on every page or a drop on
    every page instead of once at a single boundary."""
    expected = _seed_corpus(db_conn, 9)

    seen = _walk(client, page_size=1, params={"category": FILTER_CATEGORY})

    _assert_exactly_once(seen, expected)


def test_filtered_total_on_page_one_agrees_with_the_walk(client, db_conn, seed_taxonomy):
    """``meta.filteredTotal`` and the pages come from two different SQL statements
    (the count drops the freshness join). If they disagree, the UI's "N jobs"
    header describes a set the user can never finish scrolling to — or promises
    fewer than it delivers."""
    expected = _seed_corpus(db_conn, 11)

    first = client.get(
        SEARCH_URL, params={"status": "OPEN", "category": FILTER_CATEGORY, "limit": 4}
    )
    assert first.status_code == 200, first.text
    assert first.json()["meta"]["filteredTotal"] == len(expected)

    seen = _walk(client, page_size=4, params={"category": FILTER_CATEGORY})
    assert len(seen) == first.json()["meta"]["filteredTotal"]


# ---------------------------------------------------------------------------
# (2) Ties on first_seen_at
# ---------------------------------------------------------------------------


def test_rows_sharing_first_seen_at_break_the_tie_on_source_id_then_id(
    client, db_conn, seed_taxonomy
):
    """The realistic collision: a company's first scrape stamps ONE
    ``first_seen_at`` across its whole board, and the enricher then labels the lot
    with the same category — so an entire filtered page can share a timestamp.

    Without the ``(source_id, id)`` PK tiebreak, a ``first_seen_at``-only boundary
    either loops forever (``<=`` — the same rows come back) or skips the remainder
    of the block (``<`` — everything sharing that instant is excluded after the
    first page). Page size 3 against a 10-row tie guarantees the boundary lands
    INSIDE the tie, and the ids are deliberately reused across two sources so the
    tuple's uniqueness, not the id's, is what makes the walk deterministic.
    """
    shared = BASE_TIME
    keys: list[tuple[str, str]] = []
    for source_id, company in ((SourceId.GOOGLE, "google"), (SourceId.APPLE, "apple")):
        for n in range(5):
            keys.append(
                _insert_row(
                    db_conn,
                    f"tied-{n:02d}",  # same id under two sources, on purpose
                    shared,
                    category=FILTER_CATEGORY,
                    source_id=source_id,
                    company=company,
                )
            )
        # A decoy sharing the exact instant: the tiebreak must not be allowed to
        # walk onto a row the filter excludes.
        _insert_row(
            db_conn,
            "tied-decoy",
            shared,
            category=OTHER_CATEGORY,
            source_id=source_id,
            company=company,
        )
    # All timestamps are equal, so the DESC order is decided purely by the
    # tiebreak: source_id DESC, then id DESC.
    expected = sorted(keys, reverse=True)

    seen = _walk(client, page_size=3, params={"category": FILTER_CATEGORY})

    _assert_exactly_once(seen, expected)


# ---------------------------------------------------------------------------
# (3) The walk under concurrent mutation — the reason keyset exists
# ---------------------------------------------------------------------------


def test_inserts_at_the_head_mid_walk_do_not_corrupt_later_pages(
    client, db_conn, seed_taxonomy
):
    """A scrape landing mid-walk must be EXCLUDED, not interleaved.

    Every intruder here matches the active filter and carries a ``first_seen_at``
    newer than the walk's starting point, so under the DESC ordering it belongs
    strictly *ahead* of the cursor and the row-value predicate drops it by
    construction. Under offset paging the same inserts would shift every later
    page down and silently re-serve (or skip) one real row per insert.

    Asserting the ABSENCE of the intruders is the load-bearing half — a walk that
    included them would still look fine: more results, no error.
    """
    expected = _seed_corpus(db_conn, 18)
    intruders: list[tuple[str, str]] = []

    def insert_newer(page_index: int) -> None:
        intruders.append(
            _insert_row(
                db_conn,
                f"intruder-{page_index:02d}",
                # Newer than every seeded row, so it sorts ahead of the cursor.
                BASE_TIME + timedelta(days=10 + page_index),
                category=FILTER_CATEGORY,
            )
        )

    seen = _walk(
        client,
        page_size=5,
        params={"category": FILTER_CATEGORY},
        between_pages=insert_newer,
    )

    _assert_exactly_once(seen, expected)
    assert intruders, "the test did not actually insert anything mid-walk"
    for key in intruders:
        assert key not in seen, (
            f"{key} was inserted after the walk started, at a position ahead of the "
            "cursor, and must not appear in a later page"
        )


def test_deletes_behind_the_cursor_mid_walk_do_not_skip_unread_rows(
    client, db_conn, seed_taxonomy
):
    """Close-detection removing rows the walk has ALREADY served must not shift the
    pages it has not.

    Under offset paging each such delete pulls one unread row backwards past the
    offset and drops it with no error. Under keyset the cursor names a row, not a
    count, so the remaining pages are unaffected.
    """
    expected = _seed_corpus(db_conn, 18)
    deleted: set[tuple[str, str]] = set()

    def delete_already_served(page_index: int) -> None:
        # expected[page_index] is at the head of the DESC order — served on page 1
        # — i.e. strictly ahead of wherever the cursor now sits.
        target = expected[page_index]
        with db_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM job_listings WHERE source_id = %s AND id = %s", target
            )
        db_conn.commit()
        deleted.add(target)

    seen = _walk(
        client,
        page_size=5,
        params={"category": FILTER_CATEGORY},
        between_pages=delete_already_served,
    )

    assert deleted, "the test did not actually delete anything mid-walk"
    assert len(seen) == len(set(seen)), "deletes ahead of the cursor caused duplicates"
    # Every row not deleted before the walk reached it must still appear once.
    still_expected = [k for k in expected if k not in deleted or k in seen]
    _assert_exactly_once(seen, still_expected)


def test_a_row_enriched_into_the_filter_mid_walk_is_not_revisited(
    client, db_conn, seed_taxonomy
):
    """The failure mode unique to a SERVER-side filter: the matching set itself
    changes under the reader.

    The enricher labels rows continuously, so a job that was NULL-category (and
    therefore invisible to this filter) on page 1 can carry the filtered category
    by page 3. This one sits at the very head of the ordering — already passed by
    the cursor — so once it joins the filtered set it must simply not appear: the
    walk enumerates the set as it existed at the position it has reached, and
    re-serving a row from behind the cursor would hand the client a duplicate it
    has no way to detect.

    (The mirror case — a row enriched *ahead* of the cursor, which the walk will
    reach later and legitimately return — is not a defect and is not asserted
    against; a keyset walk is a complete enumeration of the set at its own
    position, not a snapshot.)
    """
    expected = _seed_corpus(db_conn, 15)
    # Newest row in the corpus, unenriched: page 1 must not contain it.
    latecomer = _insert_row(
        db_conn, "latecomer", BASE_TIME + timedelta(days=30), category=None
    )
    enriched_after_page: list[int] = []

    def enrich_the_latecomer(page_index: int) -> None:
        if page_index != 0:
            return
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE job_listings SET enrichment_category = %s"
                " WHERE source_id = %s AND id = %s",
                (FILTER_CATEGORY, *latecomer),
            )
        db_conn.commit()
        enriched_after_page.append(page_index)

    seen = _walk(
        client,
        page_size=4,
        params={"category": FILTER_CATEGORY},
        between_pages=enrich_the_latecomer,
    )

    assert enriched_after_page == [0], "the mid-walk enrichment never ran"
    assert latecomer not in seen, (
        "a row that gained the filtered category BEHIND the cursor was served "
        "anyway — the walk re-read territory it had already passed"
    )
    _assert_exactly_once(seen, expected)


# ---------------------------------------------------------------------------
# (4) The nextCursor contract
# ---------------------------------------------------------------------------


def test_next_cursor_points_at_the_last_row_of_the_page_just_served(
    client, db_conn, seed_taxonomy
):
    """The token must encode the page's TAIL under the ACTIVE filter.

    Encoding the head — or the tail of the unfiltered corpus, which is the decoy
    row sitting just after this page's last match — would re-serve or skip a
    page's worth of rows on the next call, with a 200 either way.
    """
    expected = _seed_corpus(db_conn, 10)
    params = {"status": "OPEN", "category": FILTER_CATEGORY, "limit": 4}

    first = client.get(SEARCH_URL, params=params)
    assert first.status_code == 200, first.text
    page = first.json()["jobs"]
    tail = page[-1]

    decoded = decode_search_cursor(
        first.json()["nextCursor"],
        expected_fingerprint=_fingerprint(category=[FILTER_CATEGORY]),
    )
    assert (decoded.source_id, decoded.job_id) == (tail["sourceId"], tail["id"])
    assert decoded.first_seen_at == datetime.fromisoformat(tail["firstSeenAt"])
    assert (decoded.source_id, decoded.job_id) == expected[3]

    # And following it resumes at the next MATCH, not the next row in the table.
    second = client.get(SEARCH_URL, params={**params, "cursor": first.json()["nextCursor"]})
    assert second.status_code == 200, second.text
    resumed = [(job["sourceId"], job["id"]) for job in second.json()["jobs"]]
    assert resumed == expected[4:8]


def test_changing_page_size_mid_walk_keeps_the_walk_complete(
    client, db_conn, seed_taxonomy
):
    """``limit`` is deliberately excluded from the cursor fingerprint, so a client
    that shrinks or grows its page size mid-walk stays valid. This asserts the
    consequence that matters — the walk is still an exact enumeration — rather
    than merely that the request returns 200."""
    expected = _seed_corpus(db_conn, 12)
    params = {"status": "OPEN", "category": FILTER_CATEGORY}

    seen: list[tuple[str, str]] = []
    cursor: str | None = None
    for page_size in (5, 2, 7, 9):
        query = {**params, "limit": page_size}
        if cursor is not None:
            query["cursor"] = cursor
        resp = client.get(SEARCH_URL, params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen.extend((job["sourceId"], job["id"]) for job in body["jobs"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert cursor is None, "the walk should have ended within four pages"
    _assert_exactly_once(seen, expected)


# ---------------------------------------------------------------------------
# (5) The exact SQL — the paging shape, captured
# ---------------------------------------------------------------------------


class _CapturingCursor:
    """Records the fully-composed SQL text handed to psycopg2."""

    def __init__(self, inner, conn, sink: list):
        self._inner = inner
        self._conn = conn
        self._sink = sink

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)

    def execute(self, query, params=None):
        text = query.as_string(self._conn)
        # Session-tuning statements are not the query under test. `search_jobs`
        # and `get_search_counts` each issue a `SET LOCAL jit = off` first (JIT
        # compilation costs more than the whole query for a multi-term keyword
        # OR-chain), and capturing it would shift every index-based assertion
        # below by one.
        if not text.strip().upper().startswith("SET "):
            self._sink.append((text, list(params or [])))
        return self._inner.execute(query, params)

    def fetchall(self):
        return self._inner.fetchall()

    def fetchone(self):
        return self._inner.fetchone()


class _CapturingConnection:
    def __init__(self, inner):
        self._inner = inner
        self.executed: list = []

    def cursor(self, *args, **kwargs):
        return _CapturingCursor(
            self._inner.cursor(*args, **kwargs), self._inner, self.executed
        )


def test_the_page_query_orders_by_the_keyset_tuple_and_seeks_with_a_row_value_predicate(
    db_conn, seed_taxonomy
):
    """The three textual facts the whole paging contract rests on, asserted against
    the SQL actually sent to Postgres:

    * the ORDER BY is the keyset tuple — not the legacy ``f.last_seen_at DESC``,
      which churns on every scrape and would make the cursor boundary unrelated to
      the ordering it names;
    * the boundary is a single ROW-VALUE comparison, not a hand-expanded
      ``a < x OR (a = x AND ...)`` chain, which is the classic place a tiebreak
      gets dropped and rows go missing; and
    * there is no OFFSET anywhere — reintroducing one alongside a cursor would seek
      to the boundary and then discard rows past it, a 200 with silent loss.
    """
    _seed_corpus(db_conn, 2)
    spy = _CapturingConnection(db_conn)

    search_service.search_jobs(
        spy,
        limit=25,
        status="OPEN",
        categories=[FILTER_CATEGORY],
        cursor=JobCursor(BASE_TIME, SourceId.GOOGLE, "m-0001"),
    )

    assert len(spy.executed) == 1
    actual_sql, actual_params = spy.executed[0]

    assert (
        "ORDER BY job_listings.first_seen_at DESC, job_listings.source_id DESC,"
        " job_listings.id DESC" in actual_sql
    ), actual_sql
    assert "f.last_seen_at DESC" not in actual_sql
    assert (
        "(job_listings.first_seen_at, job_listings.source_id, job_listings.id)"
        " < (%s, %s, %s)" in actual_sql
    ), actual_sql
    assert "OFFSET" not in actual_sql.upper(), actual_sql
    # The cursor tuple is bound in sort-key order, and last — an ordering swap here
    # (source_id/id transposed) type-checks, executes, and pages wrongly in silence.
    assert actual_params[-4:] == [BASE_TIME, SourceId.GOOGLE, "m-0001", 25]


def test_a_single_category_is_an_equality_not_a_one_element_any(db_conn, seed_taxonomy):
    """Load-bearing for the plan tests below, and invisible in every result-based
    test: ``= ANY(ARRAY['x'])`` returns identical rows to ``= 'x'`` but the planner
    will not treat it as an ordered equality seek on
    ``idx_job_listings_open_category_keyset``, so the endpoint silently reverts to
    scanning the unenriched majority of the corpus."""
    _seed_corpus(db_conn, 2)
    spy = _CapturingConnection(db_conn)

    search_service.search_jobs(spy, limit=25, status="OPEN", categories=[FILTER_CATEGORY])
    single_sql, _ = spy.executed[0]
    assert "job_listings.enrichment_category = %s" in single_sql, single_sql

    spy.executed.clear()
    search_service.search_jobs(
        spy, limit=25, status="OPEN", categories=[FILTER_CATEGORY, OTHER_CATEGORY]
    )
    multi_sql, _ = spy.executed[0]
    assert "job_listings.enrichment_category = ANY(%s::text[])" in multi_sql, multi_sql


# ---------------------------------------------------------------------------
# (6) The plan at prod-like scale
# ---------------------------------------------------------------------------

# Prod cardinality and enrichment mix as of 2026-08-10, measured, not guessed:
# 31,236 OPEN rows distributed
#   NULL 64.6% | software_engineering 20.8% | business_ops 9.3% |
#   hardware_engineer 3.3% | product_manager 0.7% | data_scientist 0.7% |
#   growth 0.7% | project_manager 0.0%
# Reproduced here (server-side, one statement) because index selection is a COST
# decision — at fixture scale the planner rightly seq-scans everything, so a
# 30-row test cannot tell a working index from a missing one.
_SCALE_OPEN_ROWS = 30_000
_SCALE_CLOSED_ROWS = 3_000
_SCALE_TOTAL_ROWS = _SCALE_OPEN_ROWS + _SCALE_CLOSED_ROWS

# The facet the plan tests probe with. NOT the largest slug, and that is a
# measured decision rather than a convenience: at this corpus shape the planner
# switches to ``idx_job_listings_open_category_keyset`` somewhere between 9% and
# 3.5% selectivity. Above that it prefers a backward scan of
# ``idx_job_listings_open_first_seen_keyset`` with the category as a heap Filter —
# a defensible choice (at 20% selectivity that scan reads ~5 index entries per
# output row, all sequential, against 1 random heap fetch per row through the
# category index), and the same choice it makes whether the fixture's
# ``first_seen_at`` is perfectly heap-correlated or scrambled down to prod's
# measured 0.46. So this file pins the index where it is load-bearing — the
# narrow facets, which are also the ones the index was added for (see the index's
# own rationale in ``db_models.py``: "a narrow filter is the worst case rather
# than the best one") — and does not pretend the planner takes it universally.
_SCALE_PLAN_CATEGORY = "hardware_engineer"

# Seeded in the taxonomy, assigned to ZERO rows — as in prod, where
# ``project_manager`` has no OPEN listings at all. The "user picked a facet
# nothing matches" case, which must still be an index probe rather than a full
# scan that finds nothing the expensive way.
_SCALE_EMPTY_CATEGORY = "project_manager"


def _seed_at_prod_scale(conn) -> None:
    """Seed prod-like cardinality, sparsity and skew in one statement.

    Four properties shape the plan and are therefore deliberate:

    * ``details`` is padded so the heap stays wide — the real table is
      TOAST-heavy, which is what makes an ordered index scan worth taking;
    * ``first_seen_at`` spans ~10 months with three rows per distinct timestamp,
      so the ``(source_id, id)`` tiebreak is exercised rather than bypassed;
    * 64.6% of rows have a NULL ``enrichment_category`` — the unenriched majority
      the category index exists to skip; and
    * the category assignment is scattered across the physical order (the
      ``g * 7919`` permutation), not clustered in runs. Clustering would give
      ``enrichment_category`` an artificially high heap correlation and hand the
      category index a cheaper random-access estimate than it deserves.

    ``first_seen_at`` IS left perfectly heap-correlated, unlike prod (0.46). That
    direction is safe: it makes the competing ``first_seen`` scan look as cheap as
    it possibly can, so every "the planner still chose the category index"
    assertion below is conservative. Verified by re-running these plans against a
    scrambled variant (correlation 0.70) — identical index choices throughout.
    """
    companies = [f"co{n:03d}" for n in range(50)]
    sources = [
        SourceId.GREENHOUSE,
        SourceId.ASHBY,
        SourceId.LEVER,
        SourceId.GEM,
        SourceId.GOOGLE,
        SourceId.APPLE,
        SourceId.MICROSOFT,
    ]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_listings (
                id, title, company, location, url, source_id, details,
                created_at, status, first_seen_at, details_scraped,
                experience_level, is_remote_eligible,
                enrichment_category, enrichment_level, enrichment_status
            )
            SELECT
                'scale-' || g,
                'Software Engineer ' || g,
                (%s::text[])[1 + (g %% %s)],
                'Somewhere, XX',
                'https://example.test/' || g,
                (%s::text[])[1 + (g %% %s)],
                jsonb_build_object('description', repeat('x', 2000), 'n', g),
                now() - (g || ' minutes')::interval,
                CASE WHEN g > %s THEN 'OPEN' ELSE 'CLOSED' END,
                now() - (((%s - g) / 3) * interval '15 minutes'),
                TRUE, 'mid', FALSE,
                CASE
                    WHEN (g * 7919) %% 1000 < 646 THEN NULL
                    WHEN (g * 7919) %% 1000 < 854 THEN 'software_engineering'
                    WHEN (g * 7919) %% 1000 < 947 THEN 'business_ops'
                    WHEN (g * 7919) %% 1000 < 980 THEN 'hardware_engineer'
                    WHEN (g * 7919) %% 1000 < 987 THEN 'product_manager'
                    WHEN (g * 7919) %% 1000 < 994 THEN 'data_scientist'
                    ELSE 'growth'
                END,
                CASE
                    WHEN (g * 7919) %% 1000 < 646 THEN NULL
                    WHEN (g * 7919) %% 100 < 4 THEN 'intern'
                    ELSE 'mid'
                END,
                CASE WHEN (g * 7919) %% 1000 < 646 THEN NULL ELSE 'done' END
            FROM generate_series(1, %s) AS g
            """,
            (
                companies,
                len(companies),
                sources,
                len(sources),
                _SCALE_CLOSED_ROWS,
                _SCALE_TOTAL_ROWS,
                _SCALE_TOTAL_ROWS,
            ),
        )
        cur.execute("ANALYZE job_listings")
        cur.execute("ANALYZE job_freshness")
        cur.execute("ANALYZE companies")
    conn.commit()


def _explain(
    conn, *, categories: list[str] | None = None, cursor: JobCursor | None = None,
    limit: int = 100,
) -> str:
    """EXPLAIN the query the endpoint actually issues, built from the production
    fragments rather than a hand-written approximation — so a change to the SQL
    that breaks the plan cannot slip past by leaving this test's copy intact."""
    where, params = search_service.build_search_where(
        status="OPEN", categories=categories, cursor=cursor
    )
    query = sql.SQL("SELECT {} FROM {}{} {} {} LIMIT %s").format(
        db_service._LIST_COLUMNS,
        db_service._JOBS_TABLE,
        db_service._FRESHNESS_JOIN,
        where,
        db_service._KEYSET_ORDER_BY,
    )
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("EXPLAIN ") + query, params)
        rows = cur.fetchall()
    conn.rollback()
    return "\n".join(
        row[0] if isinstance(row, tuple) else list(row.values())[0] for row in rows
    )


def _index_conds(plan: str) -> str:
    return "\n".join(line for line in plan.splitlines() if "Index Cond:" in line)


# The Sort node that must NOT exist is the one implementing THIS query's ordering.
# Asserted by its sort key rather than by the bare word "Sort", because the
# per-row ``locations`` subplan in _LIST_COLUMNS legitimately sorts its own handful
# of tag rows (``Sort Key: jl.is_primary DESC, l.canonical_name``) whenever the
# catalog is big enough to make a nested loop win — it does on prod. Matching the
# word alone would fail there for a reason that has nothing to do with paging.
_KEYSET_SORT_NODE = "Sort Key: job_listings.first_seen_at"


def _assert_no_keyset_sort(plan: str) -> None:
    assert _KEYSET_SORT_NODE not in plan, (
        "the planner materialized and sorted the matching set instead of walking "
        f"it in index order — the page is a slice of an unbounded query:\n{plan}"
    )


@pytest.fixture
def prod_scale_corpus(db_conn, seed_taxonomy):
    """Function-scoped because ``clean_tables`` truncates before every test; the
    seed has to be re-run per test rather than shared."""
    _seed_at_prod_scale(db_conn)
    return None


@pytest.mark.slow
def test_a_single_category_page_seeks_the_category_index_without_sorting(
    db_conn, prod_scale_corpus
):
    """The performance contract of this endpoint, asserted rather than asserted-in-
    a-comment.

    ``idx_job_listings_open_category_keyset`` leads with the category equality and
    continues with the sort tuple, so the planner can seek straight to the slug and
    scan it BACKWARD in sort order. Two things prove that happened and only the
    plan can show them: the index is named with the category as an ``Index Cond``,
    and there is **no Sort node for this query's ordering**. A Sort would mean the
    endpoint materializes every matching row before applying LIMIT — paging the
    result of an unbounded query, which is the shape this endpoint exists to
    remove.
    """
    plan = _explain(db_conn, categories=[_SCALE_PLAN_CATEGORY])

    assert (
        "Index Scan Backward using idx_job_listings_open_category_keyset" in plan
    ), plan
    assert "enrichment_category" in _index_conds(plan), (
        f"the category must be a seek, not a heap Filter:\n{plan}"
    )
    _assert_no_keyset_sort(plan)


@pytest.mark.slow
def test_a_mid_walk_cursor_under_a_category_is_an_index_condition_not_a_filter(
    db_conn, prod_scale_corpus
):
    """The row-value predicate must reach the index as an ``Index Cond``.

    If it degrades to a ``Filter``, every page still returns the RIGHT rows — so no
    correctness test in this file catches it — but page N first walks and discards
    the preceding N x limit index entries, and the walk becomes quadratic. That is
    offset paging with extra steps, wearing a cursor.
    """
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT first_seen_at, source_id, id FROM job_listings"
            " WHERE status = 'OPEN' AND enrichment_category = %s"
            " ORDER BY first_seen_at DESC, source_id DESC, id DESC"
            " OFFSET 600 LIMIT 1",
            (_SCALE_PLAN_CATEGORY,),
        )
        row = cur.fetchone()
    db_conn.rollback()
    assert row is not None, "fixture did not produce a deep-enough walk position"
    boundary = JobCursor(row["first_seen_at"], row["source_id"], row["id"])

    plan = _explain(db_conn, categories=[_SCALE_PLAN_CATEGORY], cursor=boundary)

    assert "idx_job_listings_open_category_keyset" in plan, plan
    index_cond = _index_conds(plan)
    assert "ROW(" in index_cond.upper(), (
        "the cursor tuple must be an Index Cond (a seek), not a Filter "
        f"(a scan-and-discard):\n{plan}"
    )
    assert "enrichment_category" in index_cond, (
        f"the category equality must lead the index seek:\n{plan}"
    )
    _assert_no_keyset_sort(plan)


@pytest.mark.slow
def test_a_no_facet_page_still_uses_the_unfiltered_keyset_index(db_conn, prod_scale_corpus):
    """Adding the category index must not cost the unfiltered case anything: with
    no facet selected there is nothing to seek on, and the page has to come from a
    backward scan of ``idx_job_listings_open_first_seen_keyset`` — the same plan
    ``/api/jobs`` gets. This is the default view of the Recent page, so a
    regression here is a regression for every visitor."""
    plan = _explain(db_conn)

    assert (
        "Index Scan Backward using idx_job_listings_open_first_seen_keyset" in plan
    ), plan
    _assert_no_keyset_sort(plan)


@pytest.mark.slow
def test_a_category_matching_nothing_probes_the_index_instead_of_scanning(
    db_conn, prod_scale_corpus
):
    """A well-formed slug with zero rows is NOT an error — it just matches nothing.
    It must also not be the most expensive request the endpoint serves: without an
    index probe, "no results" costs a walk of the whole OPEN corpus to discover the
    obvious, which is exactly the request a user hammering an empty facet repeats.

    Deliberately does NOT pin WHICH index answers it. With no matching rows the
    planner costs ``idx_job_listings_open_category_keyset`` and the older
    ``idx_job_listings_status_category`` within ~5% of each other (measured: 50.6
    vs 52.9) and picks either run to run — a coin flip between two probes that both
    return in microseconds. The invariant with teeth is that neither degrades into
    a scan of the table, and that the slug reaches an index at all rather than
    being applied as a heap Filter after the fact.
    """
    plan = _explain(db_conn, categories=[_SCALE_EMPTY_CATEGORY])

    assert "Seq Scan on job_listings" not in plan, (
        f"an empty facet fell back to a full table scan:\n{plan}"
    )
    assert "enrichment_category" in _index_conds(plan), (
        f"the empty facet was applied as a heap Filter, not an index probe:\n{plan}"
    )


@pytest.mark.slow
def test_a_multi_category_page_still_avoids_sorting_the_whole_match_set(
    db_conn, prod_scale_corpus
):
    """Selecting two categories keeps a LIMIT-friendly ordered plan.

    The category dropdown is a multi-select, so this is a first-class shape, and
    it deliberately does NOT get the same plan as the single-category case:
    `= ANY(...)` on the leading column of
    ``idx_job_listings_open_category_keyset`` cannot produce globally ordered
    output (btree runs one primitive scan per array element), so the planner
    falls back to the unfiltered keyset index and applies the categories as a
    heap filter.

    That is fine, and this test exists to say which part is fine. What must NOT
    happen is a bitmap scan plus a Sort of every matching row: that would
    materialize the full result set before LIMIT, which is precisely the
    "paginate an unbounded query" shape this endpoint replaced. The ordered scan
    short-circuits at LIMIT instead.
    """
    plan = _explain(db_conn, categories=[_SCALE_PLAN_CATEGORY, "growth"])

    assert "Index Scan Backward using idx_job_listings_open_first_seen_keyset" in plan, plan
    _assert_no_keyset_sort(plan)
    assert "Seq Scan on job_listings" not in plan, plan
