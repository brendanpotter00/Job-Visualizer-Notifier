"""Paging-correctness tests for keyset pagination on ``GET /api/jobs`` (ticket 1.3).

WHY THIS FILE IS THE DELIVERABLE
--------------------------------
Every failure mode of a paginated read path is SILENT. A broken cursor does not
500 — it returns a 200 with a plausible-looking page that is quietly missing rows,
or quietly repeating them, and the caller has no way to tell. Nothing downstream
(the SPA, the transformer, the selectors) can detect it either: a job that never
arrives simply is not in the list.

So the assertions here are deliberately about the WALK, not about individual
responses. The central invariant every walk test asserts is:

    the multiset of rows returned across all pages == the seeded set, exactly

— no duplicates, no gaps, and termination. Anything weaker (spot-checking page 1,
counting rows) would pass against a cursor that drops every third row.

The scenarios are chosen to break the two things that make offset paging unsound
on this endpoint, both of which are ROUTINE here rather than exotic:

* ``job_freshness.last_seen_at`` churn — re-stamped on every OPEN row on every
  hourly scrape cycle, i.e. constantly, mid-walk, in production.
* Concurrent inserts at the head of the ordering — every scrape cycle adds new
  listings whose ``first_seen_at`` is newer than the walk's starting point.
"""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from psycopg2 import sql

from api.pagination import JobCursor, decode_job_cursor, encode_job_cursor
from api.services import database as db_service
from scripts.shared.constants import SourceId

from .conftest import _insert_job, _make_job

# Fixed anchor so every timestamp in this module is deterministic and readable in
# failure output. Deliberately microsecond-free where it does not matter, and
# microsecond-precise where it does (see test_cursor_round_trips_microseconds).
BASE_TIME = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _seed_sequence(conn, count: int, *, company: str = "google",
                   source_id: str = SourceId.GOOGLE, status: str = "OPEN",
                   spacing: timedelta = timedelta(minutes=5),
                   start: datetime = BASE_TIME,
                   prefix: str = "job") -> list[tuple[str, str]]:
    """Seed ``count`` jobs with strictly increasing ``first_seen_at``.

    Returns the seeded ``(source_id, id)`` keys in the endpoint's DESC order
    (newest first), which is the exact order a correct walk must reproduce.
    """
    keys: list[tuple[str, str]] = []
    for n in range(count):
        job_id = f"{prefix}-{n:04d}"
        _insert_job(conn, _make_job({
            "id": job_id,
            "company": company,
            "source_id": source_id,
            "status": status,
            "first_seen_at": _iso(start + n * spacing),
            # Freshness deliberately does NOT correlate with first_seen_at, so a
            # walk that accidentally ordered by last_seen_at would produce a
            # visibly different sequence rather than coincidentally passing.
            "last_seen_at": _iso(start + (count - n) * spacing),
        }))
        keys.append((source_id, job_id))
    keys.reverse()
    return keys


def _walk(client, *, page_size: int, params: dict | None = None,
          between_pages=None) -> list[tuple[str, str]]:
    """Drive a complete keyset walk and return every ``(sourceId, id)`` seen.

    Duplicates are preserved in the returned list on purpose — de-duplicating
    here would hide the exact bug class these tests exist to catch.

    ``between_pages(page_index)`` runs after each page is fetched, which is where
    the concurrency tests mutate the table mid-walk.
    """
    base = {"status": "OPEN", **(params or {})}
    seen: list[tuple[str, str]] = []
    cursor: str | None = None
    for page_index in range(200):  # hard cap: a non-terminating walk is a failure
        query = {**base, "limit": page_size}
        if cursor is not None:
            query["cursor"] = cursor
        resp = client.get("/api/jobs", params=query)
        assert resp.status_code == 200, resp.text
        page = resp.json()
        seen.extend((job["sourceId"], job["id"]) for job in page)

        next_cursor = resp.headers.get("X-Next-Cursor")
        # The contract, asserted on every single page of every walk: the header is
        # present iff the page came back full. This is the ONLY end-of-walk
        # signal, so it is not enough to check it once at the end.
        if len(page) == page_size:
            assert next_cursor is not None, (
                f"page {page_index} was full ({len(page)} rows) but carried no "
                "X-Next-Cursor — the walk would truncate here"
            )
        else:
            assert next_cursor is None, (
                f"page {page_index} was short ({len(page)} of {page_size}) but "
                "carried X-Next-Cursor — the walk would not terminate"
            )

        if between_pages is not None:
            between_pages(page_index)

        if next_cursor is None:
            return seen
        cursor = next_cursor
    pytest.fail("walk did not terminate within 200 pages")


def _assert_exactly_once(seen: list[tuple[str, str]],
                         expected: list[tuple[str, str]]) -> None:
    """Every expected row returned exactly once, in order, and nothing else."""
    duplicates = [k for k in set(seen) if seen.count(k) > 1]
    assert not duplicates, f"rows returned more than once: {sorted(duplicates)}"
    missing = [k for k in expected if k not in seen]
    assert not missing, f"rows silently dropped by the walk: {sorted(missing)}"
    unexpected = [k for k in seen if k not in expected]
    assert not unexpected, f"rows the walk should not have seen: {sorted(unexpected)}"
    assert seen == expected, "walk returned the right rows in the wrong order"


# ---------------------------------------------------------------------------
# (1) The full paging walk
# ---------------------------------------------------------------------------


def test_full_walk_returns_every_job_exactly_once(client, db_conn):
    """37 rows / page size 7 — deliberately not a multiple, so the final page is
    partial and the walk must terminate on the missing header rather than on a
    row count."""
    expected = _seed_sequence(db_conn, 37)

    seen = _walk(client, page_size=7,
                 params={"since": _iso(BASE_TIME - timedelta(days=1))})

    _assert_exactly_once(seen, expected)
    assert len(seen) == 37


def test_full_walk_with_page_size_dividing_evenly_still_terminates(client, db_conn):
    """20 rows / page size 5. The last full page mints a cursor, so there is one
    extra round trip returning an empty array — the documented cost of not
    over-fetching. Assert that empty page is reached and ends the walk rather than
    looping forever."""
    expected = _seed_sequence(db_conn, 20)

    seen = _walk(client, page_size=5,
                 params={"since": _iso(BASE_TIME - timedelta(days=1))})

    _assert_exactly_once(seen, expected)


def test_walk_with_page_size_one_covers_every_row(client, db_conn):
    """Page size 1 maximizes the number of cursor round trips, so any
    off-by-one in the boundary predicate (``<`` vs ``<=``) shows up as either a
    duplicate on every page or a drop on every page."""
    expected = _seed_sequence(db_conn, 12)

    seen = _walk(client, page_size=1,
                 params={"since": _iso(BASE_TIME - timedelta(days=1))})

    _assert_exactly_once(seen, expected)


# ---------------------------------------------------------------------------
# (2) The walk under concurrent mutation — the reason keyset exists
# ---------------------------------------------------------------------------


def test_freshness_churn_between_pages_does_not_perturb_the_walk(client, db_conn):
    """A scrape cycle re-stamping ``job_freshness.last_seen_at`` mid-walk must be
    invisible to paging.

    This is the post-ticket-1.1 world: ``last_seen_at`` lives on the sidecar and
    is rewritten for every OPEN row every hour. If the keyset ordering keyed off
    it (as the legacy ORDER BY does), each of these updates would reshuffle the
    result set underneath the cursor and rows would slide across page boundaries
    unseen. ``first_seen_at`` is immutable, which is the whole point.
    """
    expected = _seed_sequence(db_conn, 25)

    def churn(page_index: int) -> None:
        # Reverse the freshness ordering completely between every page — a far
        # more violent perturbation than a real scrape, and still a no-op.
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE job_freshness SET last_seen_at = %s + "
                "(random() * 10000) * interval '1 second'",
                (BASE_TIME + timedelta(days=page_index + 1),),
            )
        db_conn.commit()

    seen = _walk(client, page_size=6,
                 params={"since": _iso(BASE_TIME - timedelta(days=1))},
                 between_pages=churn)

    _assert_exactly_once(seen, expected)


def test_inserts_at_the_head_mid_walk_do_not_corrupt_later_pages(client, db_conn):
    """New listings arriving mid-walk must be EXCLUDED, not interleaved.

    Every insert here has a ``first_seen_at`` newer than the walk's page-1 head,
    so under the DESC ordering they belong strictly *before* the cursor — and the
    row-value predicate ``(first_seen_at, source_id, id) < cursor`` excludes them
    by construction. Under offset paging the same inserts would shift every
    subsequent page down by one and silently re-serve/skip rows.

    Asserting the *absence* of the intruders is the load-bearing half: a walk that
    included them would still "look fine" (more results, no error).
    """
    expected = _seed_sequence(db_conn, 24)
    intruders: list[tuple[str, str]] = []

    def insert_newer(page_index: int) -> None:
        job_id = f"intruder-{page_index:02d}"
        _insert_job(db_conn, _make_job({
            "id": job_id,
            "company": "google",
            "source_id": SourceId.GOOGLE,
            "status": "OPEN",
            # Newer than every seeded row (which top out at BASE_TIME + 23*5min).
            "first_seen_at": _iso(BASE_TIME + timedelta(days=10 + page_index)),
            "last_seen_at": _iso(BASE_TIME + timedelta(days=10 + page_index)),
        }))
        intruders.append((SourceId.GOOGLE, job_id))

    seen = _walk(client, page_size=6,
                 params={"since": _iso(BASE_TIME - timedelta(days=1))},
                 between_pages=insert_newer)

    _assert_exactly_once(seen, expected)
    assert intruders, "the test did not actually insert anything mid-walk"
    for key in intruders:
        assert key not in seen, (
            f"{key} was inserted after the walk started, at a position ahead of "
            "the cursor, and must not appear in a later page"
        )


def test_deletes_behind_the_cursor_mid_walk_do_not_skip_rows(client, db_conn):
    """Rows removed from *ahead* of the cursor (already-served territory) must not
    shift the remaining pages. Under offset paging each delete pulls one unseen
    row backwards past the offset, dropping it silently."""
    expected = _seed_sequence(db_conn, 24)
    deleted: set[tuple[str, str]] = set()

    def delete_newest_remaining(page_index: int) -> None:
        # Delete a row that has ALREADY been served (index page_index of the DESC
        # order), i.e. strictly ahead of the current cursor position.
        target = expected[page_index]
        with db_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM job_listings WHERE source_id = %s AND id = %s",
                target,
            )
        db_conn.commit()
        deleted.add(target)

    seen = _walk(client, page_size=6,
                 params={"since": _iso(BASE_TIME - timedelta(days=1))},
                 between_pages=delete_newest_remaining)

    # Everything not deleted before it was reached must still appear exactly once.
    assert len(seen) == len(set(seen)), "deletes ahead of the cursor caused duplicates"
    still_expected = [k for k in expected if k not in deleted or k in seen]
    _assert_exactly_once(seen, still_expected)


# ---------------------------------------------------------------------------
# (3) Tie-breaking on a shared first_seen_at
# ---------------------------------------------------------------------------


def test_rows_sharing_first_seen_at_page_correctly_across_the_boundary(client, db_conn):
    """The realistic collision case: a company's first scrape stamps one
    ``first_seen_at`` on its entire board.

    Without the ``(source_id, id)`` PK tiebreak, ``first_seen_at``-only keyset
    paging on a block of identical timestamps either loops forever (``<=``, the
    same rows come back) or skips the rest of the block (``<``, everything with
    that timestamp is excluded after the first page). Page size 3 against a
    9-row block guarantees the boundary lands INSIDE the tie.
    """
    shared = BASE_TIME
    keys: list[tuple[str, str]] = []
    for n in range(9):
        job_id = f"tied-{n:02d}"
        _insert_job(db_conn, _make_job({
            "id": job_id,
            "company": "google",
            "source_id": SourceId.GOOGLE,
            "status": "OPEN",
            "first_seen_at": _iso(shared),
            "last_seen_at": _iso(shared),
        }))
        keys.append((SourceId.GOOGLE, job_id))
    # All timestamps equal, so the DESC order is decided purely by the tiebreak:
    # source_id DESC then id DESC.
    expected = sorted(keys, reverse=True)

    seen = _walk(client, page_size=3, params={"since": _iso(shared)})

    _assert_exactly_once(seen, expected)


def test_ties_spanning_multiple_source_ids_break_on_source_then_id(client, db_conn):
    """Same instant, different sources — pins that ``source_id`` is the second
    sort column and that the two together are unique, so ids colliding across
    sources cannot shadow each other."""
    shared = BASE_TIME
    keys: list[tuple[str, str]] = []
    for source_id in (SourceId.GOOGLE, SourceId.APPLE):
        for n in range(4):
            # Deliberately the SAME id under two different sources: job ids are
            # only unique within a source, and the composite PK is what makes the
            # keyset tuple unique.
            job_id = f"dup-{n:02d}"
            _insert_job(db_conn, _make_job({
                "id": job_id,
                "company": "google" if source_id == SourceId.GOOGLE else "apple",
                "source_id": source_id,
                "status": "OPEN",
                "first_seen_at": _iso(shared),
                "last_seen_at": _iso(shared),
            }))
            keys.append((source_id, job_id))
    expected = sorted(keys, reverse=True)

    seen = _walk(client, page_size=3, params={"since": _iso(shared)})

    _assert_exactly_once(seen, expected)


# ---------------------------------------------------------------------------
# (4) `since` bound semantics
# ---------------------------------------------------------------------------


def test_since_is_inclusive_at_the_exact_boundary(client, db_conn):
    """``first_seen_at >= since``. The row sitting exactly ON the bound is IN;
    the row one microsecond earlier is OUT. Pinned explicitly because an
    off-by-one-microsecond here is invisible in every realistic dataset and would
    only ever surface as one missing job."""
    boundary = datetime(2026, 5, 1, 12, 0, 0, 500000, tzinfo=timezone.utc)
    for label, moment in (
        ("before", boundary - timedelta(microseconds=1)),
        ("exact", boundary),
        ("after", boundary + timedelta(microseconds=1)),
    ):
        _insert_job(db_conn, _make_job({
            "id": label, "company": "google", "source_id": SourceId.GOOGLE,
            "status": "OPEN", "first_seen_at": _iso(moment),
            "last_seen_at": _iso(moment),
        }))

    resp = client.get("/api/jobs", params={
        "status": "OPEN", "since": _iso(boundary), "limit": 50,
    })
    assert resp.status_code == 200
    returned = {job["id"] for job in resp.json()}

    assert returned == {"exact", "after"}, (
        "`since` must be inclusive of the boundary instant and exclude anything "
        "strictly before it"
    )


def test_since_accepts_z_suffix_and_offsets_and_normalizes_to_utc(client, db_conn):
    """``Z``, ``+00:00`` and a non-UTC offset naming the same instant must all
    select the same rows — otherwise the window silently depends on how the
    caller spelled the time."""
    boundary = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    _seed_sequence(db_conn, 6, start=boundary)

    spellings = [
        "2026-05-01T12:00:00Z",
        "2026-05-01T12:00:00+00:00",
        "2026-05-01T07:00:00-05:00",  # same instant, CDT
    ]
    results = []
    for spelling in spellings:
        resp = client.get("/api/jobs", params={
            "status": "OPEN", "since": spelling, "limit": 50,
        })
        assert resp.status_code == 200, f"{spelling}: {resp.text}"
        results.append([job["id"] for job in resp.json()])

    assert results[0] == results[1] == results[2]
    assert len(results[0]) == 6


def test_since_alone_switches_ordering_to_first_seen_at(client, db_conn):
    """``since`` with no cursor still uses the keyset ordering — otherwise page 1
    of a walk would be ordered by ``last_seen_at`` and the first cursor minted
    from it would point at the wrong boundary."""
    expected = _seed_sequence(db_conn, 8)

    resp = client.get("/api/jobs", params={
        "status": "OPEN", "since": _iso(BASE_TIME - timedelta(days=1)),
        "limit": 50,
    })
    assert resp.status_code == 200
    seen = [(job["sourceId"], job["id"]) for job in resp.json()]

    # _seed_sequence gives last_seen_at the OPPOSITE ordering to first_seen_at,
    # so this assertion fails loudly if the legacy ORDER BY leaked through.
    assert seen == expected


def test_since_composes_with_the_companies_filter(client, db_conn):
    """Scope guard: the existing ``companies`` filter keeps working alongside the
    new bound, and the walk stays complete within the filtered set."""
    google = _seed_sequence(db_conn, 10, company="google",
                            source_id=SourceId.GOOGLE, prefix="g")
    _seed_sequence(db_conn, 10, company="apple", source_id=SourceId.APPLE,
                   prefix="a")

    seen = _walk(client, page_size=4, params={
        "since": _iso(BASE_TIME - timedelta(days=1)), "companies": "google",
    })

    _assert_exactly_once(seen, google)


def test_status_filter_composes_with_cursors(client, db_conn):
    """Documented behaviour: ``status`` ANDs into the keyset predicate normally.
    ``CLOSED`` + cursor falls off the partial index but must still be CORRECT."""
    _seed_sequence(db_conn, 8, status="OPEN", prefix="open")
    closed = _seed_sequence(db_conn, 8, status="CLOSED", prefix="closed")

    seen: list[tuple[str, str]] = []
    cursor = None
    for _ in range(20):
        query = {"status": "CLOSED", "limit": 3,
                 "since": _iso(BASE_TIME - timedelta(days=1))}
        if cursor:
            query["cursor"] = cursor
        resp = client.get("/api/jobs", params=query)
        assert resp.status_code == 200
        seen.extend((j["sourceId"], j["id"]) for j in resp.json())
        cursor = resp.headers.get("X-Next-Cursor")
        if cursor is None:
            break

    _assert_exactly_once(seen, closed)


# ---------------------------------------------------------------------------
# (5) Fail-loud validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_cursor,reason", [
    ("!!!not-base64!!!", "malformed base64"),
    ("~~~~", "base64 alphabet violation"),
    (base64.urlsafe_b64encode(b"\xff\xfe\xfd\xfc").decode().rstrip("="),
     "valid base64 that is not UTF-8"),
    (base64.urlsafe_b64encode(b"2026-05-01T12:00:00+00:00").decode().rstrip("="),
     "one field, no separators"),
    (base64.urlsafe_b64encode(b"2026-05-01T12:00:00+00:00|google_scraper")
     .decode().rstrip("="), "two fields, missing the id"),
    (base64.urlsafe_b64encode(b"not-a-timestamp|google_scraper|job-1")
     .decode().rstrip("="), "unparseable timestamp"),
    (base64.urlsafe_b64encode(b"2026-05-01T12:00:00|google_scraper|job-1")
     .decode().rstrip("="), "naive timestamp with no UTC offset"),
    (base64.urlsafe_b64encode(b"2026-13-45T99:00:00+00:00|google_scraper|job-1")
     .decode().rstrip("="), "out-of-range date components"),
    (base64.urlsafe_b64encode(b"2026-05-01T12:00:00+00:00|bad source!|job-1")
     .decode().rstrip("="), "source_id outside the controlled vocabulary"),
    (base64.urlsafe_b64encode(b"2026-05-01T12:00:00+00:00|google_scraper|")
     .decode().rstrip("="), "empty id"),
    ("", "empty cursor"),
])
def test_malformed_cursor_is_a_422_not_a_silent_page_one(
    client, db_conn, bad_cursor, reason
):
    """A cursor the server cannot understand MUST fail loudly.

    The dangerous alternative is not a crash — it is ignoring the parameter and
    serving page 1 with a 200. To the client that is indistinguishable from a
    correct response, so a paging loop would restart forever (or, with a
    mid-walk cursor, silently re-serve rows it already had).
    """
    _seed_sequence(db_conn, 5)

    resp = client.get("/api/jobs", params={
        "status": "OPEN", "cursor": bad_cursor, "limit": 3,
    })

    assert resp.status_code == 422, (
        f"{reason}: expected 422, got {resp.status_code} — a rejected cursor "
        f"must never fall back to page 1. Body: {resp.text[:300]}"
    )
    assert "cursor" in resp.text.lower(), (
        f"{reason}: the 422 detail must name the offending parameter"
    )


def test_over_long_cursor_is_rejected_by_the_query_length_bound(client, db_conn):
    """FastAPI's ``max_length`` rejects before any decode work happens."""
    _seed_sequence(db_conn, 3)
    resp = client.get("/api/jobs", params={"cursor": "A" * 5000, "limit": 3})
    assert resp.status_code == 422


@pytest.mark.parametrize("bad_since,reason", [
    ("yesterday", "not a timestamp at all"),
    ("2026-05-01", "date only, no time or offset"),
    ("2026-05-01T12:00:00", "naive — no UTC offset"),
    ("2026-13-01T12:00:00Z", "month out of range"),
    ("", "empty string"),
])
def test_malformed_since_is_a_422(client, db_conn, bad_since, reason):
    """Same fail-loud rule as ``cursor``: an ignored ``since`` would silently
    widen the window to everything, which at prod scale is the unbounded query
    this ticket exists to eliminate."""
    _seed_sequence(db_conn, 5)

    resp = client.get("/api/jobs", params={
        "status": "OPEN", "since": bad_since, "limit": 3,
    })

    assert resp.status_code == 422, f"{reason}: got {resp.status_code}"
    assert "since" in resp.text.lower()


# Instants that parse fine but OVERFLOW when shifted to UTC. `astimezone` raises
# OverflowError — NOT a ValueError — so before the guard in parse_utc_timestamp
# these escaped both call sites and surfaced as a public 500.
_OVERFLOWING_INSTANTS = [
    ("0001-01-01T00:00:00+14:00", "min datetime shifted before year 1"),
    ("9999-12-31T23:59:59-14:00", "max datetime shifted past year 9999"),
    ("0001-01-01T00:00:00+00:01", "one minute of eastward offset at the floor"),
]


@pytest.mark.parametrize("raw,reason", _OVERFLOWING_INSTANTS)
def test_since_that_parses_then_overflows_is_a_422_not_a_500(
    client, db_conn, raw, reason
):
    _seed_sequence(db_conn, 3)
    resp = client.get("/api/jobs", params={"since": raw, "limit": 3})
    assert resp.status_code == 422, f"{reason}: got {resp.status_code} — {resp.text[:200]}"
    assert "since" in resp.text.lower()


@pytest.mark.parametrize("raw,reason", _OVERFLOWING_INSTANTS)
def test_cursor_that_parses_then_overflows_is_a_422_not_a_500(
    client, db_conn, raw, reason
):
    """Same class of input on the cursor path, which has its own decoder and its
    own call-site handler — so it needs its own coverage, not an assumption that
    fixing one fixed both."""
    _seed_sequence(db_conn, 3)
    payload = f"{raw}|{SourceId.GOOGLE}|job-0001".encode()
    bad_cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")

    resp = client.get("/api/jobs", params={"cursor": bad_cursor, "limit": 3})

    assert resp.status_code == 422, f"{reason}: got {resp.status_code} — {resp.text[:200]}"
    assert "cursor" in resp.text.lower()


def test_source_id_with_a_trailing_newline_is_rejected(db_conn):
    """`$` in a Python regex also matches before a trailing newline, so a
    `$`-anchored check would accept "google_scraper\\n" — a cursor that validates
    and then matches no row. The pattern is `\\Z`-anchored for this reason."""
    payload = f"2026-05-01T12:00:00+00:00|{SourceId.GOOGLE}\n|job-1".encode()
    bad_cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    with pytest.raises(Exception) as exc_info:
        decode_job_cursor(bad_cursor)
    assert "source_id" in str(exc_info.value)


def test_encode_rejects_a_source_id_that_cannot_round_trip(db_conn):
    """Encode and decode must agree. A `source_id` containing the separator would
    mint a cursor that decodes into different fields than it was built from, so the
    next page would resume from a position nobody chose — fail at mint time."""
    moment = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="round-trip"):
        encode_job_cursor(moment, "bad|source", "job-1")


def test_naive_since_is_rejected_rather_than_assumed_utc(client, db_conn):
    """Explicitly pinned as its own test because "helpfully" assuming UTC is the
    tempting fix. It would make the window boundary depend on the server's
    ``TimeZone`` GUC — an environment-dependent result set with no error."""
    _seed_sequence(db_conn, 3)
    resp = client.get("/api/jobs", params={"since": "2026-05-01T12:00:00"})
    assert resp.status_code == 422
    assert "timezone" in resp.text.lower() or "offset" in resp.text.lower()


# ---------------------------------------------------------------------------
# (6) The X-Next-Cursor contract
# ---------------------------------------------------------------------------


def test_next_cursor_present_on_a_full_page_absent_on_a_partial_one(client, db_conn):
    _seed_sequence(db_conn, 7)
    params = {"status": "OPEN", "since": _iso(BASE_TIME - timedelta(days=1))}

    full = client.get("/api/jobs", params={**params, "limit": 5})
    assert full.status_code == 200
    assert len(full.json()) == 5
    assert full.headers.get("X-Next-Cursor") is not None

    partial = client.get("/api/jobs", params={**params, "limit": 50})
    assert partial.status_code == 200
    assert len(partial.json()) == 7
    assert partial.headers.get("X-Next-Cursor") is None


def test_next_cursor_points_at_the_last_row_of_the_page(client, db_conn):
    """The token must encode the page's TAIL. Encoding the head (or any other
    row) would re-serve or skip a whole page's worth of rows on the next call."""
    _seed_sequence(db_conn, 10)

    resp = client.get("/api/jobs", params={
        "status": "OPEN", "since": _iso(BASE_TIME - timedelta(days=1)), "limit": 4,
    })
    page = resp.json()
    tail = page[-1]

    decoded = decode_job_cursor(resp.headers["X-Next-Cursor"])
    assert decoded.source_id == tail["sourceId"]
    assert decoded.job_id == tail["id"]
    assert decoded.first_seen_at == datetime.fromisoformat(tail["firstSeenAt"])


def test_legacy_request_never_emits_a_next_cursor(client, db_conn):
    """No ``since``, no ``cursor`` -> no header, even on an exactly-full page.

    The legacy path is ordered by ``last_seen_at``; a cursor minted from its tail
    would name a position in a DIFFERENT ordering, and following it would skip an
    arbitrary slice of the table. Emitting nothing is the only safe answer.
    """
    _seed_sequence(db_conn, 10)

    resp = client.get("/api/jobs", params={"status": "OPEN", "limit": 5})

    assert resp.status_code == 200
    assert len(resp.json()) == 5, "page is exactly full — the tempting case"
    assert resp.headers.get("X-Next-Cursor") is None


def test_cursor_round_trips_microsecond_precision(client, db_conn):
    """Postgres timestamps are microsecond-precision. A cursor that truncated to
    seconds would land the boundary between two real rows: every row sharing that
    second either repeats or vanishes."""
    moment = datetime(2026, 5, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
    encoded = encode_job_cursor(moment, SourceId.GOOGLE, "job-1")
    assert decode_job_cursor(encoded).first_seen_at == moment

    # And through the wire: two rows one microsecond apart must not collapse.
    for n, label in ((0, "first"), (1, "second")):
        _insert_job(db_conn, _make_job({
            "id": label, "company": "google", "source_id": SourceId.GOOGLE,
            "status": "OPEN",
            "first_seen_at": _iso(moment + timedelta(microseconds=n)),
            "last_seen_at": _iso(moment),
        }))

    seen = _walk(client, page_size=1, params={"since": _iso(moment)})
    assert seen == [(SourceId.GOOGLE, "second"), (SourceId.GOOGLE, "first")]


def test_cursor_survives_a_job_id_containing_the_field_separator(db_conn):
    """Job ids are opaque ATS strings. Splitting greedily on ``|`` would make any
    id containing one un-pageable — a per-row cliff in the middle of a walk."""
    moment = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    weird_id = "req|123|abc"
    decoded = decode_job_cursor(
        encode_job_cursor(moment, SourceId.GOOGLE, weird_id)
    )
    assert decoded.job_id == weird_id
    assert decoded.source_id == SourceId.GOOGLE


def test_cursor_tolerates_base64_padding_from_the_caller(db_conn):
    """``encode`` strips ``=`` padding; a caller that re-adds it (or a proxy that
    normalizes it) must still be understood rather than 422'd mid-walk."""
    moment = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    stripped = encode_job_cursor(moment, SourceId.GOOGLE, "job-1")
    padded = stripped + "=" * (-len(stripped) % 4)
    assert decode_job_cursor(padded) == decode_job_cursor(stripped)


# ---------------------------------------------------------------------------
# (7) The legacy path is byte-identical
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
        self._sink.append((query.as_string(self._conn), list(params or [])))
        return self._inner.execute(query, params)

    def fetchall(self):
        return self._inner.fetchall()


class _CapturingConnection:
    def __init__(self, inner):
        self._inner = inner
        self.executed: list = []

    def cursor(self, *args, **kwargs):
        return _CapturingCursor(
            self._inner.cursor(*args, **kwargs), self._inner, self.executed
        )


def test_legacy_call_emits_the_exact_pre_keyset_sql(db_conn):
    """The regression lock on "neither ``since`` nor ``cursor`` changes the ORDER BY".

    The ORDER BY template below is copied VERBATIM from the pre-keyset revision
    (2cbb7e0, ``services/database.py::get_jobs``). It is intentionally a literal
    and NOT built from the new ``_LEGACY_ORDER_BY`` constant — reusing the
    constant would make this test agree with any future edit to it, which is
    exactly what it exists to prevent.

    The COLUMN list, by contrast, is taken from ``_TREND_LIST_COLUMNS`` (not the
    literal pre-keyset projection): Wave-1 B3 thinned the ``/api/jobs`` legacy read
    to drop the per-row ``tags`` subquery (nothing on that path reads it), and this
    test locks the ORDER BY / keyset shape, not the projection — so it tracks the
    trend column constant deliberately.
    """
    _seed_sequence(db_conn, 3)
    spy = _CapturingConnection(db_conn)

    db_service.get_jobs(spy, companies=["google"], status="OPEN", limit=25, offset=0)

    assert len(spy.executed) == 1
    actual_sql, actual_params = spy.executed[0]

    where, expected_params = db_service._build_where(
        company=None, status="OPEN", companies=["google"],
        category=None, level=None, exclude_hidden_companies=True,
        # E7 leak fix: the public read now ALSO excludes private
        # visibility='user' companies unconditionally. This is a permanent
        # predicate on the public path, not keyset machinery — the ORDER BY and
        # everything else below stays the pre-keyset shape.
        exclude_user_companies=True,
    )
    expected_sql = sql.SQL(
        "SELECT {} FROM {}{} {} ORDER BY f.last_seen_at DESC LIMIT %s OFFSET %s"
    ).format(
        db_service._TREND_LIST_COLUMNS, db_service._JOBS_TABLE,
        db_service._FRESHNESS_JOIN, where,
    ).as_string(db_conn)
    expected_params.extend([25, 0])

    assert actual_sql == expected_sql
    assert actual_params == expected_params
    # Belt and braces: none of the keyset machinery may leak into this path.
    assert "first_seen_at DESC" not in actual_sql
    assert "ROW(" not in actual_sql.upper()


def test_keyset_call_switches_the_order_by_and_adds_the_row_predicate(db_conn):
    """The mirror image: with a cursor, the legacy ORDER BY must be GONE. Leaving
    it in place while applying a ``first_seen_at`` boundary is the single worst
    outcome available here — a 200 whose page boundary is unrelated to its
    ordering."""
    _seed_sequence(db_conn, 3)
    spy = _CapturingConnection(db_conn)
    cursor = decode_job_cursor(
        encode_job_cursor(BASE_TIME, SourceId.GOOGLE, "job-0001")
    )

    db_service.get_jobs(spy, status="OPEN", limit=25,
                        since=BASE_TIME - timedelta(days=1), cursor=cursor)

    actual_sql, _ = spy.executed[0]
    assert "ORDER BY f.last_seen_at DESC" not in actual_sql
    assert (
        "ORDER BY job_listings.first_seen_at DESC, job_listings.source_id DESC,"
        " job_listings.id DESC" in actual_sql
    )
    assert (
        "(job_listings.first_seen_at, job_listings.source_id, job_listings.id)"
        " < (%s, %s, %s)" in actual_sql
    )
    assert "job_listings.first_seen_at >= %s" in actual_sql


# ---------------------------------------------------------------------------
# (7b) offset is incompatible with keyset paging
# ---------------------------------------------------------------------------


def test_offset_zero_is_accepted_alongside_a_cursor(client, db_conn):
    """`offset=0` is the default and a no-op, so it must not trip the guard —
    rejecting it would break any client that sends its defaults explicitly."""
    _seed_sequence(db_conn, 8)
    since = _iso(BASE_TIME - timedelta(days=1))

    first = client.get("/api/jobs", params={
        "status": "OPEN", "since": since, "limit": 4, "offset": 0,
    })
    assert first.status_code == 200
    cursor = first.headers["X-Next-Cursor"]

    second = client.get("/api/jobs", params={
        "status": "OPEN", "cursor": cursor, "limit": 4, "offset": 0,
    })
    assert second.status_code == 200
    assert len(second.json()) == 4


@pytest.mark.parametrize("extra", [
    {"since": _iso(BASE_TIME - timedelta(days=1))},
    {"cursor": encode_job_cursor(BASE_TIME, SourceId.GOOGLE, "job-0003")},
    {"since": _iso(BASE_TIME - timedelta(days=1)),
     "cursor": encode_job_cursor(BASE_TIME, SourceId.GOOGLE, "job-0003")},
])
def test_nonzero_offset_with_keyset_params_is_a_422(client, db_conn, extra):
    """`get_jobs` appends `LIMIT %s OFFSET %s` for BOTH orderings, so a cursor plus
    a non-zero offset would seek to the boundary and then throw away the first
    `offset` rows after it — a 200 with silently missing rows, which is the entire
    failure mode this endpoint is being hardened against. Reject rather than
    silently ignore `offset`."""
    _seed_sequence(db_conn, 8)

    resp = client.get("/api/jobs", params={
        "status": "OPEN", "limit": 3, "offset": 2, **extra,
    })

    assert resp.status_code == 422, resp.text[:300]
    assert "offset" in resp.text.lower()


def test_legacy_offset_is_untouched(client, db_conn):
    """Scope guard: with neither keyset param, `offset` behaves exactly as before."""
    _seed_sequence(db_conn, 10)

    page = client.get("/api/jobs", params={"status": "OPEN", "limit": 10})
    assert page.status_code == 200
    all_ids = [job["id"] for job in page.json()]

    skipped = client.get("/api/jobs", params={
        "status": "OPEN", "limit": 10, "offset": 3,
    })
    assert skipped.status_code == 200
    assert [job["id"] for job in skipped.json()] == all_ids[3:]


def test_legacy_response_is_unchanged_by_this_pr(client, db_conn):
    """End-to-end shape check on the untouched path: still a bare JSON array,
    still ordered by ``last_seen_at`` DESC, still no pagination header."""
    _seed_sequence(db_conn, 6)

    resp = client.get("/api/jobs", params={"status": "OPEN", "limit": 50})

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    last_seen = [job["lastSeenAt"] for job in body]
    assert last_seen == sorted(last_seen, reverse=True)
    assert "X-Next-Cursor" not in resp.headers


# ---------------------------------------------------------------------------
# (8) The plan at prod-like scale
# ---------------------------------------------------------------------------

# Prod cardinality as of 2026-08-05: 67,650 job_listings of which ~29,500 OPEN.
# Reproduced here (server-side, via generate_series) because index selection is a
# COST decision — at fixture scale the planner rightly seq-scans everything, so a
# 20-row test could not tell a working index from a missing one.
_SCALE_TOTAL_ROWS = 67_650
_SCALE_OPEN_ROWS = 29_500


def _seed_at_prod_scale(conn) -> None:
    """Seed prod-like cardinality in one server-side statement.

    ``details`` is padded so the heap stays wide (the real table is TOAST-heavy),
    ``first_seen_at`` spans ~2 years with three rows per distinct timestamp, and
    OPEN skews recent — all three shape the plan the planner picks.
    """
    companies = [f"co{n:03d}" for n in range(50)]
    sources = [SourceId.GREENHOUSE, SourceId.ASHBY, SourceId.LEVER,
               SourceId.GEM, SourceId.GOOGLE, SourceId.APPLE, SourceId.MICROSOFT]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_listings (
                id, title, company, location, url, source_id, details,
                created_at, status, first_seen_at, details_scraped,
                experience_level, is_remote_eligible
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
                CASE WHEN g > (%s - %s) THEN 'OPEN' ELSE 'CLOSED' END,
                now() - (((%s - g) / 3) * interval '46 minutes'),
                TRUE, 'mid', FALSE
            FROM generate_series(1, %s) AS g
            """,
            (companies, len(companies), sources, len(sources),
             _SCALE_TOTAL_ROWS, _SCALE_OPEN_ROWS, _SCALE_TOTAL_ROWS,
             _SCALE_TOTAL_ROWS),
        )
        cur.execute("ANALYZE job_listings")
        cur.execute("ANALYZE job_freshness")
        cur.execute("ANALYZE companies")
    conn.commit()


def _explain(conn, since: datetime, cursor=None, limit: int = 50) -> str:
    """EXPLAIN the query the router actually issues, built from the production
    SQL fragments rather than a hand-written approximation."""
    where, params = db_service._build_where(
        companies=[f"co{n:03d}" for n in range(50)], status="OPEN",
        exclude_hidden_companies=True, since=since, cursor=cursor,
    )
    query = sql.SQL("SELECT {} FROM {}{} {} {} LIMIT %s OFFSET %s").format(
        # ``get_jobs`` emits the trend-scoped projection (Wave-1 B3 — tags dropped);
        # mirror it so this EXPLAINs the query the router actually issues.
        db_service._TREND_LIST_COLUMNS, db_service._JOBS_TABLE,
        db_service._FRESHNESS_JOIN, where, db_service._KEYSET_ORDER_BY,
    )
    params.extend([limit, 0])
    with conn.cursor() as cur:
        cur.execute(sql.SQL("EXPLAIN ") + query, params)
        rows = cur.fetchall()
    conn.rollback()
    return "\n".join(
        row[0] if isinstance(row, tuple) else list(row.values())[0] for row in rows
    )


@pytest.mark.slow
def test_first_page_uses_the_keyset_index_with_no_sort_at_prod_scale(db_conn):
    """The performance contract, asserted rather than asserted-in-a-comment.

    Two things must hold, and only the plan can show them:

    * the scan is ``Index Scan Backward using
      idx_job_listings_open_first_seen_keyset`` — the all-ASC composite index
      really does serve the all-DESC ORDER BY backwards, which is the assumption
      the index definition rests on;
    * there is **no Sort node**. A Sort here would mean the endpoint materializes
      and sorts every row in the ``since`` window before applying LIMIT — i.e. the
      unbounded behaviour this ticket exists to remove, hiding behind a paged API.
    """
    _seed_at_prod_scale(db_conn)
    since = datetime.now(timezone.utc) - timedelta(days=90)

    plan = _explain(db_conn, since)

    assert "idx_job_listings_open_first_seen_keyset" in plan, plan
    assert "Index Scan Backward using idx_job_listings_open_first_seen_keyset" in plan, plan
    assert "Sort Key" not in plan, f"the planner introduced a Sort node:\n{plan}"


@pytest.mark.slow
def test_mid_walk_cursor_is_an_index_condition_not_a_filter(db_conn):
    """The row-value predicate must reach the index as an ``Index Cond``.

    If it degrades to a ``Filter``, every page still returns the RIGHT rows — so
    no correctness test catches it — but page N costs a scan of the preceding
    N x limit index entries, and the walk becomes quadratic. That is the offset
    behaviour with extra steps.
    """
    _seed_at_prod_scale(db_conn)
    since = datetime.now(timezone.utc) - timedelta(days=90)
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT first_seen_at, source_id, id FROM job_listings"
            " WHERE status = 'OPEN' AND first_seen_at >= %s"
            " ORDER BY first_seen_at DESC, source_id DESC, id DESC"
            " OFFSET 2000 LIMIT 1",
            (since,),
        )
        row = cur.fetchone()
    db_conn.rollback()
    assert row is not None, "fixture did not produce a deep-enough walk position"
    boundary = (row["first_seen_at"], row["source_id"], row["id"])

    plan = _explain(db_conn, since, cursor=JobCursor(*boundary))

    assert "Index Scan Backward using idx_job_listings_open_first_seen_keyset" in plan, plan
    index_cond = next(
        (line for line in plan.splitlines() if "Index Cond:" in line), ""
    )
    assert "ROW(" in index_cond.upper(), (
        "the cursor tuple must be an Index Cond (a seek), not a Filter "
        f"(a scan-and-discard):\n{plan}"
    )
    assert "Sort Key" not in plan, f"the planner introduced a Sort node:\n{plan}"
