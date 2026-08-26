"""E7 unit 10 — the title-overlap SUGGESTION, and the D6 guarantee that it never merges.

Two things are pinned here and they are not the same weight.

1. **The bar.** ≥70% of the smaller title set, both sets ≥20 titles, ≥20 shared. Each rail
   is pinned on BOTH sides at its boundary, because a threshold that is only tested from
   the passing side is a threshold nobody can safely change.

2. **D6 — never merge.** ``test_a_merge_is_never_performed`` and
   ``test_find_published_match_writes_nothing_at_all`` are the executable form of the one
   decision this whole unit exists to respect: there is no un-merge path in this codebase,
   no merge audit, and no way to reconstruct which rows came from which board, so a false
   merge is permanent and silent while a false suggestion is one dismissible banner. The
   first test snapshots every ``job_listings`` row and every ``companies`` row and asserts
   the ONLY difference the whole path can produce is the suggestion blob on the private
   row's own ``provider_config``. The second traps every statement the comparison executes
   and asserts they are all SELECTs.

The 70% number itself is evidence-backed, not chosen: scored across all 9,045 pairs of the
135 production companies, the worst FALSE pair clearing the ≥20 floor reaches 20.0%, the
mean is 1.08%, and no pair reaches even 30%. The measured true pair (Spotify) sits at 86%.
The module docstring carries the full write-up.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg2 import sql

from api.services import published_board_match as pbm
from api.services.published_board_match import (
    MIN_SHARED_TITLES,
    MIN_TITLE_SET,
    OVERLAP_THRESHOLD,
    find_published_match,
    normalize_title,
    read_suggestion,
    score_overlap,
    suggest_published_board,
    title_set,
)
from scripts.shared.constants import custom

# --- seeding ------------------------------------------------------------------------


def _insert_company(
    conn, company_id: str, *, visibility: str, enabled: bool = True, display_name=None
) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility, "
            "provider_config) VALUES (%s, %s, %s, %s, %s, %s, '{{}}'::jsonb)"
        ).format(sql.Identifier("companies")),
        (
            company_id,
            display_name or company_id.title(),
            "greenhouse" if visibility == "public" else "discovered",
            company_id,
            enabled,
            visibility,
        ),
    )
    conn.commit()


def _insert_jobs(conn, company_id: str, titles, *, source_id=None, status="OPEN") -> None:
    """One OPEN row per title. ``source_id`` defaults to the custom namespace."""
    src = source_id if source_id is not None else custom(company_id)
    cur = conn.cursor()
    for i, title in enumerate(titles):
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (id, title, company, url, source_id, created_at, "
                "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(sql.Identifier("job_listings")),
            (
                f"{company_id}-{i}", title, company_id, f"https://x/{company_id}/{i}",
                src, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", status,
            ),
        )
    conn.commit()


def _titles(prefix: str, n: int, start: int = 0) -> list[str]:
    return [f"{prefix} Engineer {i}" for i in range(start, start + n)]


def _seed_pair(db_conn, *, candidate_titles, public_titles, public_enabled=True):
    """A private board and one enabled public company, each with its OPEN titles."""
    _insert_company(db_conn, "u-cand000001", visibility="user")
    _insert_jobs(db_conn, "u-cand000001", candidate_titles)
    _insert_company(
        db_conn, "spotify", visibility="public", enabled=public_enabled,
        display_name="Spotify",
    )
    _insert_jobs(db_conn, "spotify", public_titles, source_id="lever_api")


def _provider_config(db_conn, company_id: str):
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT provider_config FROM {} WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (company_id,),
    )
    return cur.fetchone()["provider_config"]


# --- normalization (the unit-3 dependency) -------------------------------------------


def test_normalization_folds_case_punctuation_and_html_entities() -> None:
    """The three transforms, and the one that cost a wrong measurement.

    Without the unescape, 19 of Spotify's 85 titles arrive as ``…Emerging &amp; Scaled``
    and miss their Lever twin — measured at 56/81 instead of 70/81, which is 14 points and
    enough to move a real pair from over the bar to under it.
    """
    assert normalize_title("Client Partner, Emerging &amp; Scaled") == normalize_title(
        "Client Partner - Emerging & Scaled"
    )
    assert normalize_title("Staff  Engineer") == "staff engineer"
    assert normalize_title("SENIOR ENGINEER (II)") == "senior engineer ii"
    # Total by contract — nothing about a title may raise on an unattended path.
    assert normalize_title(None) == ""
    assert normalize_title(123) == ""
    assert normalize_title("   ") == ""


def test_a_title_set_counts_each_title_once() -> None:
    """40 openings for one title is one title's worth of evidence, not forty."""
    assert title_set(["Engineer", "engineer", "ENGINEER", ""]) == frozenset({"engineer"})


# --- the measured true pair -----------------------------------------------------------


def test_the_measured_spotify_pair_produces_a_suggestion(db_conn) -> None:
    """The case that actually bit: 70 of 81 unique OPEN titles, 86%.

    Seeded exactly as measured — 81 distinct normalized OPEN titles on each side, 70 of
    them shared — and it must clear the bar with room to spare. (81 on the public side is
    what production holds today; the 85 in ``normalize_title``'s docstring is the RAW row
    count before normalization collapses duplicates.)

    It is also the test that pins the one property that made ``shared/max`` the safe
    denominator to switch to: the two sets are the SAME SIZE here, so ``min`` and ``max``
    are the same number and this pair scores 0.864 under either. The subset fix cost the
    true positive nothing at all.
    """
    shared = _titles("Shared", 70)
    _seed_pair(
        db_conn,
        candidate_titles=shared + _titles("OnlyCustom", 11),
        public_titles=shared + _titles("OnlyPublic", 11),
    )

    match = suggest_published_board(db_conn, "u-cand000001")

    assert match is not None
    assert match.company_id == "spotify"
    assert (match.shared, match.candidate_titles, match.matched_titles) == (70, 81, 81)
    assert round(match.ratio, 4) == round(70 / 81, 4)

    stored = read_suggestion(_provider_config(db_conn, "u-cand000001"))
    assert stored is not None
    assert stored["company_id"] == "spotify"
    assert stored["display_name"] == "Spotify"
    assert (stored["shared"], stored["candidate_titles"]) == (70, 81)


def test_html_entities_do_not_cost_the_match(db_conn) -> None:
    """The unit-3 dependency, end to end: the two boards spell the same titles
    differently and the comparison must not care."""
    plain = [f"Client Partner, Emerging & Scaled {i}" for i in range(25)]
    escaped = [f"Client Partner, Emerging &amp; Scaled {i}" for i in range(25)]
    _seed_pair(db_conn, candidate_titles=escaped, public_titles=plain)

    match = find_published_match(db_conn, "u-cand000001")

    assert match is not None and match.shared == 25


# --- D6: never merge ------------------------------------------------------------------


class _RecordingCursor:
    """A cursor that records the SQL it is asked to run, then runs it unchanged."""

    def __init__(self, inner, log: list[str]) -> None:
        self._inner = inner
        self._log = log

    def execute(self, query, params=None):  # noqa: ANN001 - psycopg2 signature
        self._log.append(
            query if isinstance(query, str) else query.as_string(self._inner)
        )
        return self._inner.execute(query, params)

    def __getattr__(self, name):  # noqa: ANN001
        return getattr(self._inner, name)


class _RecordingConnection:
    """A connection proxy that records every statement executed through it."""

    def __init__(self, inner) -> None:  # noqa: ANN001
        self._inner = inner
        self.statements: list[str] = []

    def cursor(self, *args, **kwargs):  # noqa: ANN001
        return _RecordingCursor(self._inner.cursor(*args, **kwargs), self.statements)

    def __getattr__(self, name):  # noqa: ANN001
        return getattr(self._inner, name)


def _first_words(statements: list[str]) -> list[str]:
    return [s.strip().split(None, 1)[0].upper() for s in statements if s.strip()]


def test_find_published_match_writes_nothing_at_all(db_conn) -> None:
    """The comparison is READ-ONLY, asserted by trapping every statement it issues.

    Half of the D6 guarantee in executable form. "This function does not write" is the
    property the whole unit rests on, and a comment is not a property.
    """
    shared = _titles("Shared", 70)
    _seed_pair(
        db_conn,
        candidate_titles=shared + _titles("OnlyCustom", 11),
        public_titles=shared + _titles("OnlyPublic", 15),
    )

    recorder = _RecordingConnection(db_conn)
    match = find_published_match(recorder, "u-cand000001")

    assert match is not None, "the fixture must actually reach the comparison"
    assert recorder.statements, "no statements recorded — the trap is not wired"
    assert set(_first_words(recorder.statements)) == {"SELECT"}


def _snapshot(db_conn) -> tuple[list[dict], list[dict]]:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM job_listings ORDER BY source_id, id")
    jobs = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM companies ORDER BY id")
    companies = [dict(r) for r in cur.fetchall()]
    return jobs, companies


def test_a_merge_is_never_performed(db_conn) -> None:
    """**DECISION D6, executable.** The strongest match we can build changes NOTHING
    except the suggestion blob on the private row's own ``provider_config``.

    Asserted against full table snapshots rather than against the response shape:

    * ``job_listings`` is byte-identical — no row moved to the public company, none
      re-pointed, none inserted, none deleted;
    * every ``companies`` row is byte-identical EXCEPT the private one, and that one
      differs in ``provider_config`` alone — its id, ats, board_token, visibility,
      enabled and display_name are untouched;
    * the PUBLIC company's row is untouched in every column, including its own
      ``provider_config`` — a merge in the other direction is a merge too.
    """
    titles = _titles("Shared", 40)
    _seed_pair(db_conn, candidate_titles=titles, public_titles=titles)

    jobs_before, companies_before = _snapshot(db_conn)
    match = suggest_published_board(db_conn, "u-cand000001")
    jobs_after, companies_after = _snapshot(db_conn)

    assert match is not None, "a 100% pair must produce the suggestion being audited"

    # 1. Not one job row was written, in either direction.
    assert jobs_after == jobs_before

    # 2. No company was inserted or deleted.
    assert [c["id"] for c in companies_after] == [c["id"] for c in companies_before]

    before_by_id = {c["id"]: c for c in companies_before}
    for after in companies_after:
        before = before_by_id[after["id"]]
        changed = {k for k in after if after[k] != before[k]}
        if after["id"] == "u-cand000001":
            # 3. The private row changed in exactly one column.
            assert changed == {"provider_config"}
        else:
            # 4. The public row — and every other row — changed in none.
            assert changed == set()

    # 5. And what landed in that one column is a suggestion, not a link.
    stored = read_suggestion(_provider_config(db_conn, "u-cand000001"))
    assert stored is not None and stored["company_id"] == "spotify"


def test_no_match_writes_nothing_at_all(db_conn) -> None:
    """A board that does NOT look like anything must leave no trace.

    Not merely "no merge" — no tombstone either. A later run finding nothing must not be
    able to resurrect or erase a suggestion the user has already dealt with.
    """
    _seed_pair(
        db_conn, candidate_titles=_titles("Custom", 40), public_titles=_titles("Public", 40)
    )

    jobs_before, companies_before = _snapshot(db_conn)
    assert suggest_published_board(db_conn, "u-cand000001") is None
    assert _snapshot(db_conn) == (jobs_before, companies_before)


# --- the bar, pinned on both sides of every rail --------------------------------------


def _score(db_conn, *, candidate: int, public: int, shared: int):
    """Seed a pair with exactly ``shared`` titles in common and return the verdict."""
    common = _titles("Shared", shared)
    _seed_pair(
        db_conn,
        candidate_titles=common + _titles("OnlyCustom", candidate - shared),
        public_titles=common + _titles("OnlyPublic", public - shared),
    )
    return find_published_match(db_conn, "u-cand000001")


def test_a_business_unit_board_inside_its_parent_is_not_a_duplicate(db_conn) -> None:
    """25 titles, ALL of them on a 1,742-title parent board. Nothing is shown.

    The subset case, at production scale and shape: ``andurilindustries`` really does carry
    1,742 distinct normalized OPEN titles, and a 25-title regional or business-unit board
    drawn from them is a real thing a user can paste. Under ``shared/min`` this scored a
    perfect **1.00** — the maximum, over every rail, shared count included (25 >= 20) — and
    fired the banner. It is the wrong answer twice over: the BU board is a SLICE of the
    parent, not a copy of it, and the parent's chart is not the chart the user asked for.

    Under ``shared/max`` the same pair scores 25/1742 = 0.014. Containment stops being
    indistinguishable from equivalence, which is the entire reason the denominator moved.
    """
    assert _score(db_conn, candidate=25, public=1742, shared=25) is None


def test_the_subset_case_is_symmetric(db_conn) -> None:
    """And the other way round: a 1,742-title board that swallows a 25-title public row.

    Same arithmetic, opposite sides. ``shared/min`` scored this 1.00 too, because it never
    looked at which set was bigger. The point of ``shared/max`` is that neither direction of
    containment can pass on its own — the overlap has to cover BOTH boards.
    """
    assert _score(db_conn, candidate=1742, public=25, shared=25) is None


def test_the_score_is_the_weaker_of_the_two_containments(db_conn) -> None:
    """The metric itself, stated as the property it has to have.

    100 shared of a 100-title candidate is 100% of the candidate — one-sided containment,
    total. The public row carries 200, so only half of IT is covered, and the score is that
    weaker half: 0.50, under the bar. Pinning the number (not just the verdict) is what
    stops the denominator quietly sliding back to ``min``, where this reads 1.00.
    """
    scored = score_overlap(
        frozenset(_titles("Shared", 100)),
        frozenset(_titles("Shared", 100) + _titles("OnlyPublic", 100)),
        company_id="spotify",
        display_name="Spotify",
    )
    assert scored.shared == 100
    assert scored.ratio == pytest.approx(0.50)
    assert not scored.qualifies
    # The EVIDENCE stays one-sided on purpose: the banner's sentence is "100 of 100 roles on
    # this board match", which is true and is about the board the user is looking at.
    assert (scored.candidate_titles, scored.matched_titles) == (100, 200)


def test_a_fifty_percent_pair_produces_nothing(db_conn) -> None:
    """Two competitors hiring the same 20 generic roles out of 40. Nothing is shown.

    The named uncertainty this unit was built under: 50% is plausible for two unrelated
    companies, so 50% must not be enough. (Measured, it is not even close — the worst
    false pair in production reaches 20%.)
    """
    assert _score(db_conn, candidate=40, public=40, shared=20) is None


def test_the_bar_is_exactly_these_three_numbers() -> None:
    """The constants themselves, pinned.

    Every boundary case below is written with LITERAL counts rather than arithmetic on
    these constants, so moving a constant makes those tests fail instead of silently
    moving with it. This test is the other half of that: it is where the intended values
    are recorded, so changing the bar is a deliberate two-line edit and shows up in the
    diff as a decision. The evidence for each number is in the module docstring.
    """
    assert OVERLAP_THRESHOLD == 0.70
    assert MIN_TITLE_SET == 20
    assert MIN_SHARED_TITLES == 20


def test_exactly_at_the_ratio_threshold_suggests(db_conn) -> None:
    """70 of 100 — the bar is ``>=``, and the boundary is pinned so a change to it is a
    test change rather than a silent behaviour change."""
    match = _score(db_conn, candidate=100, public=100, shared=70)
    assert match is not None and match.ratio == pytest.approx(0.70)


def test_one_title_below_the_ratio_threshold_suggests_nothing(db_conn) -> None:
    """69 of 100 — the other side of the same boundary."""
    assert _score(db_conn, candidate=100, public=100, shared=69) is None


def test_exactly_at_the_set_size_floor_suggests(db_conn) -> None:
    """Both sets exactly 20, fully overlapping — the smallest pair allowed to speak."""
    match = _score(db_conn, candidate=20, public=20, shared=20)
    assert match is not None and match.candidate_titles == 20


def test_a_nineteen_title_board_suggests_nothing_however_perfect(db_conn) -> None:
    """19 of 19 is 100% and must still say nothing.

    The floors are why: drop them and the worst false pair in production becomes 50.0% —
    ``appliedintuition`` × ``gem``, 2 titles out of a 4-title board. Small sets are where
    generic titles dominate and a coincidence looks like a match.
    """
    assert _score(db_conn, candidate=19, public=200, shared=19) is None


def test_a_public_board_below_the_floor_suggests_nothing(db_conn) -> None:
    """A 19-title public row cannot claim a 200-title board either."""
    assert _score(db_conn, candidate=200, public=19, shared=19) is None


def test_exactly_at_the_shared_title_floor_suggests(db_conn) -> None:
    """20 shared out of 25 — clears the ratio AND the absolute count."""
    match = _score(db_conn, candidate=25, public=25, shared=20)
    assert match is not None and match.shared == 20


def test_nineteen_shared_titles_suggest_nothing_even_at_seventy_nine_percent(db_conn) -> None:
    """19 of 24 is 79% — over the ratio bar, under the absolute one, and rejected.

    The second, independent rail, and the one that actually binds today. 18 is the most
    titles ANY two genuinely different production companies share, so a suggestion carrying
    fewer than 20 is inside the noise we measured whatever its ratio says.
    """
    assert _score(db_conn, candidate=24, public=24, shared=19) is None


# --- what is eligible to be matched ---------------------------------------------------


def test_a_disabled_public_company_is_never_suggested(db_conn) -> None:
    """A disabled public row is a board we have STOPPED reading. Sending someone from a
    live private copy to a chart that no longer updates is worse than saying nothing."""
    titles = _titles("Shared", 40)
    _seed_pair(db_conn, candidate_titles=titles, public_titles=titles, public_enabled=False)

    assert find_published_match(db_conn, "u-cand000001") is None


def test_another_private_company_is_never_suggested(db_conn) -> None:
    """Only ``visibility='public'`` rows are candidates — a second user's private board
    is not something we can point anybody at, and naming it would leak it."""
    titles = _titles("Shared", 40)
    _insert_company(db_conn, "u-cand000001", visibility="user")
    _insert_jobs(db_conn, "u-cand000001", titles)
    _insert_company(db_conn, "u-other00001", visibility="user")
    _insert_jobs(db_conn, "u-other00001", titles)

    assert find_published_match(db_conn, "u-cand000001") is None


def test_closed_jobs_are_not_compared(db_conn) -> None:
    """OPEN sets only. A CLOSED history is what the two boards USED to hold, and matching
    on it would suggest a swap on the strength of jobs neither board still lists."""
    titles = _titles("Shared", 40)
    _insert_company(db_conn, "u-cand000001", visibility="user")
    _insert_jobs(db_conn, "u-cand000001", titles)
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", titles, source_id="lever_api", status="CLOSED")

    assert find_published_match(db_conn, "u-cand000001") is None


def test_the_strongest_of_two_qualifying_matches_wins(db_conn) -> None:
    """At most one banner may be shown, so it shows the best-scoring match, not the first
    one the scan happened to reach."""
    strong = _titles("Shared", 40)
    _insert_company(db_conn, "u-cand000001", visibility="user")
    _insert_jobs(db_conn, "u-cand000001", strong)
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", strong, source_id="lever_api")
    _insert_company(db_conn, "sonos", visibility="public", display_name="Sonos")
    _insert_jobs(
        db_conn, "sonos", strong[:32] + _titles("SonosOnly", 8), source_id="ashby_api"
    )

    match = find_published_match(db_conn, "u-cand000001")

    assert match is not None and match.company_id == "spotify"


# --- the total reader -----------------------------------------------------------------


@pytest.mark.parametrize(
    "blob",
    [
        None,
        "not a mapping",
        {},
        {"public_match": "not a mapping"},
        {"public_match": {}},
        {"public_match": {"company_id": "spotify"}},
        {"public_match": {"company_id": "", "display_name": "Spotify", "shared": 1,
                          "candidate_titles": 1}},
        {"public_match": {"company_id": "spotify", "display_name": "Spotify",
                          "shared": "seventy", "candidate_titles": 81}},
        {"public_match": {"company_id": "spotify", "display_name": "Spotify",
                          "shared": True, "candidate_titles": 81}},
        {"public_match": {"company_id": "spotify", "display_name": "Spotify",
                          "shared": -1, "candidate_titles": 81}},
    ],
)
def test_an_unrenderable_blob_reads_back_as_no_suggestion(blob) -> None:
    """TOTAL BY CONTRACT. The reader runs on ``GET /api/users/companies``, the one endpoint
    the My-Companies list cannot live without, over a JSONB column an operator can edit —
    so every unrecognised shape degrades to "no banner", and none of them raises."""
    assert read_suggestion(blob) is None


def test_a_suggestion_never_clobbers_the_discovery_checklist(db_conn) -> None:
    """``jsonb_set`` of one key, not a column write. The checklist sitting beside it in the
    same blob is what a user is reading while this lands."""
    titles = _titles("Shared", 40)
    _seed_pair(db_conn, candidate_titles=titles, public_titles=titles)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET provider_config = %s::jsonb WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (json.dumps({"discovery": {"outcome": "tracking"}}), "u-cand000001"),
    )
    db_conn.commit()

    assert suggest_published_board(db_conn, "u-cand000001") is not None

    config = _provider_config(db_conn, "u-cand000001")
    assert config["discovery"] == {"outcome": "tracking"}
    assert config["public_match"]["company_id"] == "spotify"


# --- the wire -------------------------------------------------------------------------


def test_the_suggestion_reaches_the_my_companies_payload(client, db_conn, monkeypatch) -> None:
    """It rides the SAME poll the list already runs — no second channel — so the banner is
    a render of data the page already has."""
    from api.config import settings

    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)
    titles = _titles("Shared", 40)
    _seed_pair(db_conn, candidate_titles=titles, public_titles=titles)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())"
        ).format(sql.Identifier("users")),
        ("user-u10", "auth0|test_user_123", "test@example.com"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES (%s, %s, %s)"
        ).format(sql.Identifier("user_companies")),
        ("user-u10", "u-cand000001", "discovered:https://example.test/jobs"),
    )
    db_conn.commit()
    suggest_published_board(db_conn, "u-cand000001")

    body = client.get("/api/users/companies").json()

    row = next(c for c in body["companies"] if c["id"] == "u-cand000001")
    assert row["publicMatch"] == {
        "companyId": "spotify",
        "displayName": "Spotify",
        "shared": 40,
        "candidateTitles": 40,
        "detectedAt": row["publicMatch"]["detectedAt"],
    }
    assert row["publicMatch"]["detectedAt"] is not None


def test_a_company_with_no_suggestion_sends_null(client, db_conn, monkeypatch) -> None:
    """The overwhelmingly common case must render exactly what it rendered before this
    shipped."""
    from api.config import settings

    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)
    _insert_company(db_conn, "u-cand000001", visibility="user")
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())"
        ).format(sql.Identifier("users")),
        ("user-u10", "auth0|test_user_123", "test@example.com"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES (%s, %s, %s)"
        ).format(sql.Identifier("user_companies")),
        ("user-u10", "u-cand000001", "discovered:https://example.test/jobs"),
    )
    db_conn.commit()

    body = client.get("/api/users/companies").json()

    assert body["companies"][0]["publicMatch"] is None


# --- the harvest hook -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_first_verified_harvest_runs_the_comparison_and_a_later_one_does_not(
    db_conn, monkeypatch
) -> None:
    """Once per board, on the run that graduates it.

    The FIRST VERIFIED harvest is the first moment the board's OPEN set is both complete
    and PROVEN complete — an UNVERIFIED run may be a partial read, and a partial read is
    exactly how you get a spurious 100% against something it is a subset of. Re-running it
    nightly would also re-write a suggestion the user has already dismissed.
    """
    from api.config import settings
    from api.services import greenhouse_client
    from api.services.harvest_meta import HarvestEvidence
    import api.tasks.fetch_custom_company as task_mod
    from api.tasks.fetch_custom_company import fetch_custom_company

    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    configured = MagicMock()
    configured.defer_async = AsyncMock(return_value=None)
    monkeypatch.setattr(
        task_mod.normalize_location, "configure", lambda *a, **k: configured
    )

    titles = _titles("Shared", 40)

    async def _fetch(board_token, http):
        raw = [
            {
                "id": i, "title": title, "absolute_url": f"https://x/{i}",
                "location": {"name": "Remote"}, "offices": [{"name": "Remote"}],
                "departments": [{"name": "Eng"}], "metadata": [],
                "first_published": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z", "content": "<p>d</p>",
            }
            for i, title in enumerate(titles)
        ]
        return raw, HarvestEvidence.single_shot(declared_total=len(titles))

    monkeypatch.setattr(greenhouse_client, "fetch_jobs_with_meta", _fetch)

    company_id = "u-harvest001"
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'greenhouse', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), "
            "'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, "tok-u10"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, 'ats_client', 'none')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(
            {"kind": "ats_client", "provider": "greenhouse", "token": "tok-u10"}
        )),
    )
    db_conn.commit()
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", titles, source_id="lever_api")

    calls: list[str] = []
    real = pbm.suggest_published_board
    monkeypatch.setattr(
        pbm, "suggest_published_board",
        lambda conn, cid: (calls.append(cid), real(conn, cid))[1],
    )

    await fetch_custom_company(company_id=company_id)
    assert calls == [company_id], "the graduating run must run the comparison"
    stored = read_suggestion(_provider_config(db_conn, company_id))
    assert stored is not None and stored["company_id"] == "spotify"

    await fetch_custom_company(company_id=company_id)
    assert calls == [company_id], "a later harvest must NOT re-run it"


@pytest.mark.asyncio
async def test_a_failing_comparison_never_fails_the_harvest(db_conn, monkeypatch) -> None:
    """Display-only, and guarded like it. This blob decides nothing about scraping,
    closing or verifying, so it must never be able to break a harvest that worked."""
    from api.config import settings
    from api.services import greenhouse_client
    from api.services.harvest_meta import HarvestEvidence
    import api.tasks.fetch_custom_company as task_mod
    from api.tasks.fetch_custom_company import fetch_custom_company

    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    configured = MagicMock()
    configured.defer_async = AsyncMock(return_value=None)
    monkeypatch.setattr(
        task_mod.normalize_location, "configure", lambda *a, **k: configured
    )

    async def _fetch(board_token, http):
        return [
            {
                "id": 1, "title": "Engineer", "absolute_url": "https://x/1",
                "location": {"name": "Remote"}, "offices": [{"name": "Remote"}],
                "departments": [{"name": "Eng"}], "metadata": [],
                "first_published": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z", "content": "<p>d</p>",
            }
        ], HarvestEvidence.single_shot(declared_total=1)

    monkeypatch.setattr(greenhouse_client, "fetch_jobs_with_meta", _fetch)

    def _boom(conn, company_id):
        raise RuntimeError("comparison exploded")

    monkeypatch.setattr(pbm, "suggest_published_board", _boom)

    company_id = "u-harvest002"
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'greenhouse', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), "
            "'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, "tok-u10b"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, 'ats_client', 'none')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(
            {"kind": "ats_client", "provider": "greenhouse", "token": "tok-u10b"}
        )),
    )
    db_conn.commit()

    await fetch_custom_company(company_id=company_id)

    db_conn.rollback()
    cur.execute(
        sql.SQL("SELECT verdict FROM {} WHERE company_id = %s").format(
            sql.Identifier("company_harvests")
        ),
        (company_id,),
    )
    assert cur.fetchone()["verdict"] == "VERIFIED"


@pytest.mark.asyncio
async def test_a_db_error_in_the_comparison_still_leaves_the_harvest_evidence(
    db_conn, monkeypatch
) -> None:
    """The test above raises a ``RuntimeError``, which does not touch the transaction —
    so it passed even while this one would have failed.

    A *psycopg2* error is different in kind. This comparison runs on the leaf task's
    SHARED connection, and its two reads are the only DB calls on this path with no
    try/except and no rollback (``store_suggestion`` and every ``ccs.*`` helper have
    both). A statement timeout on ``_open_titles_by_public_company``'s fleet-wide seq
    scan — the realistic failure, one seq scan of a third of ``job_listings`` — leaves
    the connection in an ABORTED transaction. Logging the exception does not clear that,
    so the very next statement raises ``InFailedSqlTransaction``: and the very next
    statement is ``record_company_harvest``, whose failure is swallowed too.

    What the operator was left with: a ``scrape_runs`` row marked ``success=true``,
    VERIFIED, and NO ``company_harvests`` evidence row. This block only ever runs on the
    run that GRADUATES a board, so the single run whose evidence matters most is exactly
    the one that lost it.
    """
    from api.config import settings
    from api.services import greenhouse_client
    from api.services.harvest_meta import HarvestEvidence
    import api.tasks.fetch_custom_company as task_mod
    from api.tasks.fetch_custom_company import fetch_custom_company

    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    configured = MagicMock()
    configured.defer_async = AsyncMock(return_value=None)
    monkeypatch.setattr(
        task_mod.normalize_location, "configure", lambda *a, **k: configured
    )

    async def _fetch(board_token, http):
        return [
            {
                "id": 1, "title": "Engineer", "absolute_url": "https://x/1",
                "location": {"name": "Remote"}, "offices": [{"name": "Remote"}],
                "departments": [{"name": "Eng"}], "metadata": [],
                "first_published": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z", "content": "<p>d</p>",
            }
        ], HarvestEvidence.single_shot(declared_total=1)

    monkeypatch.setattr(greenhouse_client, "fetch_jobs_with_meta", _fetch)

    def _db_error(conn, company_id):
        """Fail the way a statement timeout does: a real psycopg2 error raised out of a
        SELECT on the shared connection, leaving the transaction aborted. Injected here
        rather than mocked so the abort is genuine — a fake exception cannot reproduce
        the state this test is about."""
        conn.cursor().execute("SELECT title FROM a_table_that_does_not_exist")

    monkeypatch.setattr(pbm, "suggest_published_board", _db_error)

    company_id = "u-harvest003"
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'greenhouse', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), "
            "'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, "tok-u10c"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, 'ats_client', 'none')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(
            {"kind": "ats_client", "provider": "greenhouse", "token": "tok-u10c"}
        )),
    )
    db_conn.commit()

    await fetch_custom_company(company_id=company_id)

    db_conn.rollback()
    cur.execute(
        sql.SQL("SELECT verdict, records_harvested FROM {} WHERE company_id = %s").format(
            sql.Identifier("company_harvests")
        ),
        (company_id,),
    )
    harvest = cur.fetchone()
    assert harvest is not None, (
        "the graduating run recorded no company_harvests evidence — a success=true "
        "scrape_run with nothing to diagnose it by"
    )
    assert harvest["verdict"] == "VERIFIED"
    assert harvest["records_harvested"] == 1

    # ...and the run itself is still recorded as the success it was.
    cur.execute(
        sql.SQL("SELECT success FROM {} WHERE company = %s").format(
            sql.Identifier("scrape_runs")
        ),
        (company_id,),
    )
    assert cur.fetchone()["success"] is True
