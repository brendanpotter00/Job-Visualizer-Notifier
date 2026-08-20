"""Wire-contract tests for ``GET /api/jobs/search``: the envelope, and the
loudness of its input validation.

WHAT THIS FILE PROTECTS
-----------------------
Two invariants, both about things the caller cannot detect for itself.

**The envelope is a promise.** ``{jobs, nextCursor, meta}`` — no more keys, no
fewer, with ``nextCursor`` present *iff* the page came back full and ``meta``
present only on page 1. Every one of those is load-bearing: ``nextCursor``'s
absence is the ONLY end-of-walk signal, so an envelope that grows a key, drops
one, or mints a token on a short page turns a correct client into one that
truncates its list or loops forever. The job objects inside must also stay
byte-compatible with ``GET /api/jobs`` (same ``EXPECTED_JOB_KEYS``), because the
frontend runs one transformer over both endpoints.

**Bad input must fail, not degrade.** This endpoint filters server-side, so a
parameter the server quietly ignores does not produce an error — it produces a
plausible 200 over a *different* corpus than the caller asked for. A dropped
``since`` silently widens the window; a dropped ``cursor`` silently restarts the
walk at page 1; a cursor honoured across a filter change enumerates neither
filter set completely. So every malformed value here is asserted to come back as
a status code with a reason attached, and the split is deliberate: **422 for a
malformed VALUE** (this string is not a timestamp / not a cursor / too long) and
**400 for structural misuse** (you sent more values than this endpoint accepts, or
an id that is not an id). The one case that is emphatically NOT an error is a
well-formed slug nobody has heard of — that is an empty result, exactly as it
would be client-side.

Ordering, filter semantics and count arithmetic live in the sibling search test
files; nothing here asserts *which* rows come back except where a decoy row is
the only way to prove a parameter was actually applied rather than swallowed.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone

import pytest

from api.pagination import encode_job_cursor
from scripts.shared.constants import SourceId

from api.routers.jobs_search import _MAX_COMPANIES, _MAX_KEYWORDS

from .conftest import _insert_job, _make_job
from .test_response_shapes import EXPECTED_JOB_KEYS

SEARCH = "/api/jobs/search"

# Fixed anchor so every seeded timestamp is deterministic and readable in failure
# output. Deliberately in the past: nothing in this file asserts the recency
# tiles' arithmetic, only that the keys carrying them exist.
BASE_TIME = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

# The whole envelope, spelled out. An assertion of equality (not containment) is
# the point — a *new* key is as much a contract break as a missing one, because
# the frontend type is exhaustive.
ENVELOPE_KEYS = {"jobs", "nextCursor", "meta"}

# Note the lowercase trailing 'h'. ``to_camel`` splits on the digit and would emit
# ``countLast24H``; models.py pins explicit aliases to stop that stray capital
# from reaching the wire, and this set is what holds that pin in place.
META_KEYS = {"filteredTotal", "countLast24h", "countLast3h"}

# A cursor from the OTHER endpoint. ``/api/jobs`` mints three fields with no
# version tag; a search cursor is five with an ``s1`` prefix. Pasting one at the
# other is a realistic copy-paste bug during a client migration, and it must be
# refused rather than half-decoded into a position nobody chose.
LEGACY_JOBS_CURSOR = encode_job_cursor(BASE_TIME, SourceId.GOOGLE, "legacy-1")


def _seed(conn, job_id: str, *, minutes_before: int = 0, **overrides) -> str:
    """Seed one job ``minutes_before`` minutes behind :data:`BASE_TIME`.

    Spacing the corpus by minutes keeps ``first_seen_at`` strictly decreasing, so
    the keyset ordering is total and page boundaries are predictable.
    """
    _insert_job(conn, _make_job({
        "id": job_id,
        "first_seen_at": (BASE_TIME - timedelta(minutes=minutes_before)).isoformat(),
        **overrides,
    }))
    return job_id


def _ids(body: dict) -> list[str]:
    return [job["id"] for job in body["jobs"]]


def _detail(resp) -> str:
    """The error reason as a flat string.

    Ours are plain strings; FastAPI's own parameter validation returns a list of
    error dicts. Flattening both lets a test assert "the reason names the thing
    that was wrong" without caring which layer rejected it.
    """
    return str(resp.json().get("detail", ""))


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


def test_response_is_an_envelope_of_jobs_next_cursor_and_meta(client, db_conn):
    _seed(db_conn, "env-1")

    body = client.get(SEARCH).json()

    assert set(body) == ENVELOPE_KEYS
    # Short page => end of walk, so the token must be absent-as-null rather than
    # simply missing: the key itself is part of the contract.
    assert body["nextCursor"] is None
    assert set(body["meta"]) == META_KEYS


def test_job_objects_carry_the_same_camel_case_keys_as_the_list_endpoint(client, db_conn):
    """The frontend runs ONE transformer over /api/jobs and /api/jobs/search.

    Compared against ``test_response_shapes.EXPECTED_JOB_KEYS`` on purpose: if
    that set ever moves, both endpoints are meant to move together, and this
    assertion fails loudly if only one of them did.
    """
    _seed(db_conn, "shape-1")

    body = client.get(SEARCH).json()

    assert set(body["jobs"][0]) == EXPECTED_JOB_KEYS


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_omitting_status_serves_the_open_feed_only(client, db_conn):
    """Unlike /api/jobs, this endpoint defaults — and the default must be OPEN.

    The CLOSED decoy is the whole test: without it, a default of "no status
    filter at all" would pass just as happily and would quietly publish dead
    listings to the Recent page.
    """
    _seed(db_conn, "open-1", minutes_before=0)
    _seed(db_conn, "closed-1", minutes_before=1, status="CLOSED")

    body = client.get(SEARCH).json()

    assert _ids(body) == ["open-1"]


def test_status_closed_serves_closed_listings_only(client, db_conn):
    _seed(db_conn, "open-2", minutes_before=0)
    _seed(db_conn, "closed-2", minutes_before=1, status="CLOSED")

    body = client.get(SEARCH, params={"status": "CLOSED"}).json()

    assert _ids(body) == ["closed-2"]


@pytest.mark.parametrize(
    "bad_status",
    [
        pytest.param("open", id="lowercase"),
        pytest.param("ARCHIVED", id="unknown_state"),
        pytest.param("OPEN,CLOSED", id="comma_joined"),
        pytest.param("", id="empty"),
    ],
)
def test_status_outside_the_two_known_states_is_rejected(client, db_conn, bad_status):
    """A typo'd status must not fall back to the default.

    Falling back would serve the OPEN feed to a caller who asked for something
    else — a 200 that answers a question nobody asked.
    """
    resp = client.get(SEARCH, params={"status": bad_status})

    assert resp.status_code == 422, resp.text
    assert "status" in _detail(resp)


# ---------------------------------------------------------------------------
# limit
# ---------------------------------------------------------------------------


def test_page_size_defaults_to_one_hundred(client, db_conn):
    """101 rows, no ``limit``: exactly 100 come back and the walk continues.

    Seeding one row past the default is what makes this a real assertion — at 100
    or fewer, any default >= the corpus size would pass.
    """
    for n in range(101):
        _seed(db_conn, f"lim-{n:03d}", minutes_before=n)

    body = client.get(SEARCH).json()

    assert len(body["jobs"]) == 100
    assert body["nextCursor"] is not None


@pytest.mark.parametrize(
    "bad_limit",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(501, id="over_ceiling"),
    ],
)
def test_limit_outside_one_through_five_hundred_is_rejected(client, db_conn, bad_limit):
    """``limit=0`` is the dangerous one: it would return an empty *full* page.

    Empty and full at once means ``nextCursor`` is minted forever while no row is
    ever served — a walk that never terminates and never progresses.
    """
    resp = client.get(SEARCH, params={"limit": bad_limit})

    assert resp.status_code == 422, resp.text
    assert "limit" in _detail(resp)


def test_limit_of_one_is_a_legal_page_size(client, db_conn):
    _seed(db_conn, "one-a", minutes_before=0)
    _seed(db_conn, "one-b", minutes_before=1)

    body = client.get(SEARCH, params={"limit": 1}).json()

    assert _ids(body) == ["one-a"]
    assert body["nextCursor"] is not None


# ---------------------------------------------------------------------------
# since
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_since",
    [
        pytest.param("2026-08-01T12:00:00", id="naive_no_offset"),
        pytest.param("yesterday", id="garbage"),
        pytest.param("2026-08-01T12:00:00+00:00" + "0" * 50, id="over_64_chars"),
    ],
)
def test_malformed_since_is_rejected_rather_than_ignored(client, db_conn, bad_since):
    """A dropped ``since`` silently widens the window instead of narrowing it.

    The naive case matters most: ``first_seen_at`` is ``timestamptz``, so an
    offset-less bound would be interpreted against the server's TimeZone GUC and
    the same request would return different rows on different deployments.
    """
    resp = client.get(SEARCH, params={"since": bad_since})

    assert resp.status_code == 422, resp.text
    assert "since" in _detail(resp)


@pytest.mark.parametrize(
    "offset_form",
    [pytest.param("Z", id="zulu"), pytest.param("+00:00", id="explicit_offset")],
)
def test_a_tz_aware_since_is_accepted_and_bounds_the_window_inclusively(
    client, db_conn, offset_form
):
    """Both spellings of UTC are the same instant, so both must be accepted.

    The row sitting exactly ON the bound is the decoy for the boundary (``>=``,
    not ``>``); the older row is the decoy for the bound being applied at all.
    """
    _seed(db_conn, "since-on-bound", minutes_before=0)
    _seed(db_conn, "since-too-old", minutes_before=60)

    bound = BASE_TIME.isoformat().replace("+00:00", offset_form)
    resp = client.get(SEARCH, params={"since": bound})

    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == ["since-on-bound"]


# ---------------------------------------------------------------------------
# cursor: malformed values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_cursor, expected_reason",
    [
        pytest.param("not-base64", "cursor", id="not_base64"),
        pytest.param("", "must not be empty", id="empty_string"),
        pytest.param(LEGACY_JOBS_CURSOR, "5", id="legacy_three_field_jobs_cursor"),
    ],
)
def test_malformed_cursor_is_rejected_rather_than_restarting_the_walk(
    client, db_conn, bad_cursor, expected_reason
):
    """A silently-discarded cursor is indistinguishable from an honoured one.

    The client would re-receive page 1, believe it was page N, and either loop
    forever or stitch a duplicate-riddled list. The empty-string case is the
    realistic one — an un-guarded template emitting ``?cursor=`` — and the legacy
    case is the copy-paste of an ``/api/jobs`` token, which carries three fields
    and no ``s1`` version tag and so cannot decode here.
    """
    _seed(db_conn, "cursor-decoy")

    resp = client.get(SEARCH, params={"cursor": bad_cursor})

    assert resp.status_code == 422, resp.text
    assert expected_reason in _detail(resp)


# ---------------------------------------------------------------------------
# cursor: the filter fingerprint
# ---------------------------------------------------------------------------


def _seed_fingerprint_corpus(conn) -> None:
    """Two google rows around one apple row, newest first.

    The interleaving is deliberate: a cursor minted under ``company=google`` names
    a position that still has rows after it under EITHER filter set, so a
    fingerprint check that silently passed would return a plausible page rather
    than an obviously empty one.
    """
    _seed(conn, "fp-newest", minutes_before=0, company="google")
    _seed(conn, "fp-middle", minutes_before=10, company="apple")
    _seed(conn, "fp-oldest", minutes_before=20, company="google")


def _mint(client, params) -> str:
    """Take page 1 under ``params`` and return the cursor it hands back."""
    resp = client.get(SEARCH, params=params)
    assert resp.status_code == 200, resp.text
    cursor = resp.json()["nextCursor"]
    assert cursor is not None, "page 1 was expected to come back full"
    return cursor


def test_a_cursor_minted_under_one_filter_set_is_refused_under_another(client, db_conn):
    """The failure this rejection exists to prevent is a *plausible* 200.

    Pages walked across a filter change enumerate neither set completely, and
    nothing downstream can tell — so the endpoint refuses, and says why.

    **409, not 422**, and the status is the contract. This rejection's ``detail``
    is addressed to the CLIENT ("drop the cursor and restart the walk from page
    1"), not to a reader who could relax a filter — and the frontend surfaces
    400/422 ``detail`` verbatim in an error box whose only affordance replays the
    same request. A distinct status is what lets the client recognize it and
    restart instead of replaying a token that will never be accepted. See
    ``StaleCursorError`` in ``api/pagination.py``.
    """
    _seed_fingerprint_corpus(db_conn)
    cursor = _mint(client, {"company": "google", "limit": 1})

    resp = client.get(SEARCH, params={"company": "apple", "limit": 1, "cursor": cursor})

    assert resp.status_code == 409, resp.text
    assert "different filter set" in _detail(resp)
    assert "restart the walk from page 1" in _detail(resp)


def test_a_cursor_is_refused_when_the_filters_are_dropped_entirely(client, db_conn):
    """Widening (removing a filter) is the same hazard as changing one.

    Worth its own case because "no filters" is the tempting thing for a client to
    fall back to when its filter state resets mid-walk.
    """
    _seed_fingerprint_corpus(db_conn)
    cursor = _mint(client, {"company": "google", "limit": 1})

    resp = client.get(SEARCH, params={"limit": 1, "cursor": cursor})

    assert resp.status_code == 409, resp.text
    assert "different filter set" in _detail(resp)


def test_a_cursor_from_an_older_format_is_a_409_not_a_422(client, db_conn):
    """A version-tag bump is the OTHER way a good client ends up holding a stale
    token, and it is the one that hits everyone at once.

    ``_SEARCH_CURSOR_VERSION`` moves in a deploy; every walk in flight at that
    moment is suddenly carrying a cursor this build will not accept. That is not a
    malformed request — the token is exactly what the previous build minted — so it
    must land in the same recoverable class as a fingerprint mismatch, or half the
    clients holding stale cursors would restart and the other half would not.

    Asserted alongside a MALFORMED cursor staying a 422, because a change that
    collapsed the two classes back together would still pass either check alone.
    """
    _seed_fingerprint_corpus(db_conn)
    good = _mint(client, {"company": "google", "limit": 1})
    # Re-mint the same five fields under a different version tag. Decoding the
    # real cursor first means every OTHER field is genuinely valid, so the version
    # check is the only thing that can reject it.
    raw = base64.urlsafe_b64decode(good + "=" * (-len(good) % 4)).decode("utf-8")
    _, fingerprint, first_seen_at, source_id, job_id = raw.split("|", 4)
    older = base64.urlsafe_b64encode(
        "|".join(("s0", fingerprint, first_seen_at, source_id, job_id)).encode("utf-8")
    ).decode("ascii").rstrip("=")

    resp = client.get(SEARCH, params={"company": "google", "limit": 1, "cursor": older})

    assert resp.status_code == 409, resp.text
    assert "restart the walk from page 1" in _detail(resp)

    # ...and a genuinely malformed token is still a 422: nothing downstream can
    # repair it, so telling the client to restart would be a lie.
    malformed = client.get(SEARCH, params={"company": "google", "cursor": "not-base64"})
    assert malformed.status_code == 422, malformed.text


def test_a_cursor_survives_a_page_size_change_mid_walk(client, db_conn):
    """``limit`` is deliberately outside the fingerprint.

    A cursor names a ROW, not an offset, so resizing pages mid-walk is correct
    keyset behaviour — folding ``limit`` into the hash would 422 a client that did
    nothing wrong (e.g. one that shrinks its page size under memory pressure).
    """
    _seed_fingerprint_corpus(db_conn)
    cursor = _mint(client, {"company": "google", "limit": 1})

    resp = client.get(SEARCH, params={"company": "google", "limit": 2, "cursor": cursor})

    assert resp.status_code == 200, resp.text
    # And the walk genuinely continued from the cursor rather than restarting.
    assert _ids(resp.json()) == ["fp-oldest"]


def test_a_cursor_survives_repeated_params_arriving_in_a_different_order(client, db_conn):
    """``?company=a&company=b`` and ``?company=b&company=a`` are the same query.

    Clients build these from a Set or an object map, so the emitted order is not
    stable between renders. An order-sensitive fingerprint would 422 at a random
    page boundary and look like a server bug.
    """
    _seed_fingerprint_corpus(db_conn)
    cursor = _mint(client, [("company", "google"), ("company", "apple"), ("limit", 1)])

    resp = client.get(
        SEARCH,
        params=[("company", "apple"), ("company", "google"), ("limit", 1),
                ("cursor", cursor)],
    )

    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == ["fp-middle"]


# ---------------------------------------------------------------------------
# Caps: too many values is structural (400), a bad value is malformed (422)
# ---------------------------------------------------------------------------


def test_more_than_twenty_category_values_is_a_structural_400(client, db_conn):
    """Every value here is well-formed, so only the CAP can be what rejected it."""
    slugs = [f"cat{chr(ord('a') + n)}" for n in range(21)]

    resp = client.get(SEARCH, params=[("category", slug) for slug in slugs])

    assert resp.status_code == 400, resp.text
    assert "at most 20" in _detail(resp)


def test_more_than_twenty_level_values_is_a_structural_400(client, db_conn):
    slugs = [f"lvl{chr(ord('a') + n)}" for n in range(21)]

    resp = client.get(SEARCH, params=[("level", slug) for slug in slugs])

    assert resp.status_code == 400, resp.text
    assert "at most 20" in _detail(resp)


def test_more_company_ids_than_the_cap_is_a_structural_400(client, db_conn):
    ids = [f"company-{n}" for n in range(_MAX_COMPANIES + 1)]

    resp = client.get(SEARCH, params=[("company", value) for value in ids])

    assert resp.status_code == 400, resp.text
    assert f"at most {_MAX_COMPANIES}" in _detail(resp)


def test_the_company_cap_clears_the_whole_roster_with_room_to_spare(client, db_conn):
    """The cap must never be reachable by an ordinary "all companies" reader.

    ``auto_enroll_new_companies`` defaults to true, so a default signed-in user
    sends ONE ``company`` param per company on the roster in a single request —
    133 enabled of 135 rows in prod on 2026-08-19. A cap sized near the roster is
    a cliff: the release that adds the company past it turns Recent Jobs into a
    hard 400 for every such reader at once, with no client-side clamp to soften
    it. Pinned as a ratio rather than a constant so growing the roster, not just
    editing the cap, is what has to argue with this test.
    """
    assert _MAX_COMPANIES >= 3 * 135, (
        "the company cap has lost its headroom over the company roster"
    )


def test_more_than_one_hundred_include_terms_is_a_structural_400(client, db_conn):
    terms = [f"term-{n}" for n in range(_MAX_KEYWORDS + 1)]

    resp = client.get(SEARCH, params=[("include", term) for term in terms])

    assert resp.status_code == 400, resp.text
    assert f"at most {_MAX_KEYWORDS}" in _detail(resp)


def test_the_keyword_cap_counts_include_and_exclude_together(client, db_conn):
    """The cap bounds the number of LIKE branches one query can build.

    Splitting the cap across the two lists would evade a per-list bound while
    costing the database exactly the same, so the check is combined.
    """
    half = _MAX_KEYWORDS // 2 + 1
    params = [("include", f"in-{n}") for n in range(half)]
    params += [("exclude", f"ex-{n}") for n in range(half)]

    resp = client.get(SEARCH, params=params)

    assert resp.status_code == 400, resp.text
    assert f"at most {_MAX_KEYWORDS}" in _detail(resp)


def test_the_keyword_cap_matches_what_a_saved_keyword_list_can_store():
    """Storage and query budgets for keywords must be ONE number.

    A saved keyword list auto-hydrates into the Recent page's filter chips on page
    load, and those chips become this endpoint's ``include``/``exclude`` params. So
    a list the user is allowed to STORE but not to QUERY is not a validation
    nicety — it is Recent Jobs returning 400 every time that user opens it, with
    no client-side clamp anywhere in the chain to soften it and nothing on screen
    but a Retry that reissues the same rejected request.
    """
    from api.models import _MAX_TAGS_PER_LIST

    assert _MAX_KEYWORDS == _MAX_TAGS_PER_LIST, (
        "a keyword list that can be saved must also be queryable; raise both or "
        "neither"
    )


def test_values_at_the_cap_boundary_are_accepted(client, db_conn):
    """The complement of the cap tests: the documented maximum is IN, not rejected.

    Without this, an off-by-one that rejected the documented maximum would sail
    through every test above.
    """
    _seed(db_conn, "cap-boundary-1")

    categories = [("category", f"cat{chr(ord('a') + n)}") for n in range(20)]
    assert client.get(SEARCH, params=categories).status_code == 200

    keywords = [("include", f"in-{n}") for n in range(_MAX_KEYWORDS // 2)]
    keywords += [("exclude", f"ex-{n}") for n in range(_MAX_KEYWORDS - _MAX_KEYWORDS // 2)]
    assert client.get(SEARCH, params=keywords).status_code == 200


@pytest.mark.parametrize(
    "field, value, expected_reason",
    [
        pytest.param("location", "x" * 201, "at most 200 characters", id="location_201_chars"),
        pytest.param("include", "x" * 101, "at most 100 characters", id="include_101_chars"),
        pytest.param("exclude", "x" * 101, "at most 100 characters", id="exclude_101_chars"),
        pytest.param("location", "", "must not be empty", id="empty_location"),
        pytest.param("include", "", "must not be empty", id="empty_include"),
        pytest.param("exclude", "", "must not be empty", id="empty_exclude"),
        pytest.param("location", "Austin\x01, TX", "control characters", id="location_control_char"),
        pytest.param("include", "remote\x7f", "control characters", id="include_control_char"),
    ],
)
def test_a_malformed_free_text_value_is_a_422_with_a_reason(
    client, db_conn, field, value, expected_reason
):
    """Empty is rejected, NOT dropped.

    ``?include=`` means the caller's template misfired; treating it as "no keyword
    filter" hands back an unfiltered result set the caller believes was filtered.
    Control characters are rejected because they would corrupt the NUL-separated
    canonical form the cursor fingerprint is hashed from.
    """
    resp = client.get(SEARCH, params={field: value})

    assert resp.status_code == 422, resp.text
    assert expected_reason in _detail(resp)


@pytest.mark.parametrize(
    "bad_company",
    [
        pytest.param("google;DROP TABLE", id="punctuation"),
        pytest.param("google job", id="whitespace"),
        pytest.param("", id="empty"),
    ],
)
def test_a_company_id_that_is_not_an_id_is_a_structural_400(client, db_conn, bad_company):
    """A company id is a controlled vocabulary, not free text.

    Anything outside its shape is a broken caller rather than a query that happens
    to match nothing, so it is refused instead of silently returning an empty feed.
    """
    resp = client.get(SEARCH, params={"company": bad_company})

    assert resp.status_code == 400, resp.text
    assert "company" in _detail(resp)


# ---------------------------------------------------------------------------
# Unknown-but-well-formed slugs are an empty result, not an error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, unknown_slug",
    [
        pytest.param("category", "underwater_basket_weaving", id="category"),
        pytest.param("level", "archmage", id="level"),
    ],
)
def test_an_unknown_but_well_formed_slug_matches_nothing_instead_of_erroring(
    client, db_conn, seed_taxonomy, field, unknown_slug
):
    """A slug the taxonomy has never heard of is a client-side no-op, not a 4xx.

    The taxonomy is data (a seeded dimension table) and can drift ahead of or
    behind any given client; erroring on an unrecognized-but-shaped value would
    turn a stale bookmark or a mid-rollout deploy into a broken page instead of an
    empty one.
    """
    _seed(db_conn, "enriched-1", enrichment_category="software_engineering",
          enrichment_level="senior")

    # The decoy: under its REAL slug the row is reachable, so an empty result
    # below is the filter working rather than the corpus being empty.
    known = {"category": "software_engineering", "level": "senior"}[field]
    assert _ids(client.get(SEARCH, params={field: known}).json()) == ["enriched-1"]

    resp = client.get(SEARCH, params={field: unknown_slug})

    assert resp.status_code == 200, resp.text
    assert resp.json()["jobs"] == []


@pytest.mark.parametrize(
    "field, bad_slug",
    [
        pytest.param("category", "Software Engineering", id="category_with_spaces"),
        # No hyphen: `_CATEGORY_RE` is `[a-z_]{1,40}`, so a hyphen is rejected on
        # its own and the digit never gets a vote. This slug is legal in every
        # respect EXCEPT the digit, so relaxing the digit rule turns it green.
        pytest.param("category", "software_engineering9", id="category_with_digits"),
        pytest.param("level", "SENIOR", id="level_uppercase"),
    ],
)
def test_a_slug_outside_the_slug_shape_is_still_a_422(client, db_conn, field, bad_slug):
    """The flip side of the test above: unknown is fine, MALFORMED is not.

    Both would return zero rows, so only the status code distinguishes "no matches"
    from "your client is sending display labels where slugs belong".
    """
    resp = client.get(SEARCH, params={field: bad_slug})

    assert resp.status_code == 422, resp.text
    assert field in _detail(resp)


# ---------------------------------------------------------------------------
# nextCursor / meta placement across a walk
# ---------------------------------------------------------------------------


def test_next_cursor_is_present_exactly_when_the_page_came_back_full(client, db_conn):
    """Present on the full page, absent on the short one — the only stop signal."""
    _seed(db_conn, "walk-a", minutes_before=0)
    _seed(db_conn, "walk-b", minutes_before=1)
    _seed(db_conn, "walk-c", minutes_before=2)

    first = client.get(SEARCH, params={"limit": 2}).json()
    assert _ids(first) == ["walk-a", "walk-b"]
    assert first["nextCursor"] is not None

    second = client.get(
        SEARCH, params={"limit": 2, "cursor": first["nextCursor"]}
    ).json()
    assert _ids(second) == ["walk-c"]
    assert second["nextCursor"] is None


def test_a_trailing_exactly_full_page_costs_one_more_empty_request(client, db_conn):
    """The accepted cost of not over-fetching with ``LIMIT limit + 1``.

    When the corpus divides evenly by the page size, the last real page is
    indistinguishable from a mid-walk page, so the client pays one extra round
    trip that returns nothing. Asserted here so nobody "fixes" the extra request
    by minting a cursor conditionally on a probe row.
    """
    _seed(db_conn, "even-a", minutes_before=0)
    _seed(db_conn, "even-b", minutes_before=1)

    first = client.get(SEARCH, params={"limit": 2}).json()
    assert _ids(first) == ["even-a", "even-b"]
    assert first["nextCursor"] is not None

    tail = client.get(SEARCH, params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert tail["jobs"] == []
    assert tail["nextCursor"] is None


def test_meta_is_computed_on_page_one_and_omitted_on_every_cursor_page(client, db_conn):
    """The counts describe the filter set, not the page.

    Recomputing them per page is pure waste — two extra aggregate queries per
    round trip — so pages 2..N carry ``meta: null`` while keeping the key.
    """
    _seed(db_conn, "meta-a", minutes_before=0)
    _seed(db_conn, "meta-b", minutes_before=1)
    _seed(db_conn, "meta-c", minutes_before=2)

    first = client.get(SEARCH, params={"limit": 2}).json()
    assert set(first) == ENVELOPE_KEYS
    assert set(first["meta"]) == META_KEYS
    assert first["meta"]["filteredTotal"] == 3

    second = client.get(SEARCH, params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert set(second) == ENVELOPE_KEYS
    assert second["meta"] is None


# ---------------------------------------------------------------------------
# Routing: /search must not shadow its siblings
# ---------------------------------------------------------------------------


def test_the_search_route_does_not_shadow_facets_or_the_job_detail_route(
    client, db_conn, seed_taxonomy
):
    """``/api/jobs/search`` is a literal sibling of ``/api/jobs/facets`` and lives
    one segment shallower than ``/api/jobs/{source_id}/{job_id}``.

    Mounting a new router under an existing prefix is exactly how a detail route
    gets swallowed, and the symptom would be a 200 with the wrong body rather than
    a 404 — so all three are asserted together, in one place, on every run.
    """
    _seed(db_conn, "route-1")

    facets = client.get("/api/jobs/facets")
    assert facets.status_code == 200, facets.text
    assert "software_engineering" in {
        option["slug"] for option in facets.json()["categories"]
    }

    detail = client.get(f"/api/jobs/{SourceId.GOOGLE}/route-1")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == "route-1"

    search = client.get(SEARCH)
    assert search.status_code == 200, search.text
    assert _ids(search.json()) == ["route-1"]


def test_every_rejection_is_logged(client, db_conn, seed_taxonomy, caplog):
    """A cap that starts firing in production must be visible in the logs.

    Both new modules bound a module logger and never called it, so a 400 was a
    bare access-log line and nothing else. Routing every rejection through
    ``_reject`` makes an unlogged one hard to add by accident; this pins that it
    stays true for a representative rejection from each class.
    """
    cases = [
        ({"company": ["!!bad!!"]}, 400),
        ({"category": ["Not-A-Slug"]}, 422),
        ({"include": [""]}, 422),
        ({"cursor": "garbage"}, 422),
    ]
    for params, expected_status in cases:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="api.routers.jobs_search"):
            response = client.get("/api/jobs/search", params=params)
        assert response.status_code == expected_status, (params, response.text)
        assert any("jobs-search rejected" in r.getMessage() for r in caplog.records), (
            f"{params} returned {expected_status} but logged nothing"
        )
