"""E7 unit 10 — the title-overlap SUGGESTION, and the D6 guarantee that it never merges.

Three things are pinned here and they are not the same weight.

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

3. **The TRIGGER, and that widening it did not widen VERIFIED.** The final section. The
   comparison used to run on the first VERIFIED harvest, which made the whole unit
   unreachable for the case it was written for: ``lifeatspotify.com`` returns its whole
   catalogue in one request, is stored ``oracle_kind='none'``, and can therefore never
   verify. It now runs on the first UNTRUNCATED harvest instead. Both halves are pinned —
   ``test_lifeatspotify_reaches_the_suggestion_end_to_end`` (it is reachable) and
   ``test_the_unverified_suggestion_run_closes_nothing_and_accrues_no_miss`` (the SAME run
   still closes nothing and is not even a miss), plus ``test_no_oracle_still_never_verifies``
   on the guardrail itself. Those two now run against a VERIFIED harvest — the
   history-delta oracle lets a single-request board verify — and still assert the same
   thing about the close path, which is what they were always for.

The 70% number itself is evidence-backed, not chosen: scored across all 9,045 pairs of the
135 production companies, the worst FALSE pair clearing the ≥20 floor reaches 20.0%, the
mean is 1.08%, and no pair reaches even 30%. The measured true pair (Spotify) sits at 86%.
The module docstring carries the full write-up.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import httpx
import psycopg2
import pytest
from psycopg2 import sql

from api.services import published_board_match as pbm
from api.tasks.fetch_custom_company import fetch_custom_company
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


def test_no_match_writes_only_the_once_latch(db_conn) -> None:
    """A board that does NOT look like anything writes the latch and NOTHING else.

    The property this has always protected, stated exactly: a later run finding nothing
    must not be able to resurrect or erase a suggestion the user has already dealt with.
    That is about the ``public_match`` key, and it is asserted below — the key is absent
    before and absent after, never written, never cleared.

    What changed is that the no-match path now writes ``public_match_checked_at``, and it
    has to. The old trigger ("first VERIFIED harvest") carried a free latch in
    ``companies.tracking_started_at``, stamped by that same run. A board that returns its
    whole catalogue in one request can never verify, so it has no such stamp, and without
    an explicit latch this comparison — a fleet-wide seq scan — would run on every harvest
    of every board forever.
    """
    _seed_pair(
        db_conn, candidate_titles=_titles("Custom", 40), public_titles=_titles("Public", 40)
    )

    jobs_before, companies_before = _snapshot(db_conn)
    assert pbm.SUGGESTION_KEY not in _provider_config(db_conn, "u-cand000001")

    assert suggest_published_board(db_conn, "u-cand000001") is None

    jobs_after, companies_after = _snapshot(db_conn)
    # Not one job row, in either direction; no company inserted or deleted.
    assert jobs_after == jobs_before
    assert [c["id"] for c in companies_after] == [c["id"] for c in companies_before]

    before_by_id = {c["id"]: c for c in companies_before}
    for after in companies_after:
        changed = {k for k in after if after[k] != before_by_id[after["id"]][k]}
        # The private row changed in ``provider_config`` alone; every other row — the
        # public company included — changed in nothing at all.
        assert changed == ({"provider_config"} if after["id"] == "u-cand000001" else set())

    config = _provider_config(db_conn, "u-cand000001")
    # And inside that one column, the ONLY key that appeared is the latch. The suggestion
    # key was never written, so nothing was resurrected and nothing was erased.
    assert set(config) == {pbm.CHECKED_KEY}
    assert isinstance(config[pbm.CHECKED_KEY], str)


def test_a_no_match_never_erases_a_suggestion_the_user_already_has(db_conn) -> None:
    """The no-tombstone rule, at its actual boundary.

    A board that HAS a stored suggestion and then stops looking like anything must keep it.
    The latch stops the comparison before it scores, so a later run cannot rewrite the
    banner's ``detected_at``, cannot swap it for a different company, and cannot delete it.
    """
    _seed_pair(
        db_conn, candidate_titles=_titles("Custom", 40), public_titles=_titles("Public", 40)
    )
    stored = {
        "company_id": "spotify", "display_name": "Spotify", "shared": 70,
        "candidate_titles": 79, "matched_titles": 81, "detected_at": "2026-01-01T00:00:00Z",
    }
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET provider_config = %s::jsonb WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (json.dumps({pbm.SUGGESTION_KEY: stored}), "u-cand000001"),
    )
    db_conn.commit()

    assert suggest_published_board(db_conn, "u-cand000001") is None

    config = _provider_config(db_conn, "u-cand000001")
    assert config[pbm.SUGGESTION_KEY] == stored
    assert pbm.CHECKED_KEY not in config, "a suggestion is its own latch; no second key"


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
async def test_the_first_untruncated_harvest_scores_the_board_and_a_later_one_does_not(
    db_conn, monkeypatch
) -> None:
    """Once per board — the comparison SCORES on one run and never again.

    Two distinct claims, and the second is the one that moved. The task now hands the
    entry point every comparable run, because ``suggest_published_board`` carries its own
    latch; what must happen exactly once is the SCORING (``find_published_match`` — the
    fleet-wide read) and the write it produces. Asserting on the entry point instead would
    now pin the plumbing rather than the property.

    Re-scoring nightly would also rewrite a suggestion the user has already dismissed with
    a fresh ``detected_at``, so the stored blob is pinned byte-for-byte across the second
    run too.
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

    scored: list[str] = []
    real_score = pbm.find_published_match
    monkeypatch.setattr(
        pbm, "find_published_match",
        lambda conn, cid: (scored.append(cid), real_score(conn, cid))[1],
    )

    await fetch_custom_company(company_id=company_id)
    assert scored == [company_id], "the first untruncated run must score the board"
    blob = _provider_config(db_conn, company_id)[pbm.SUGGESTION_KEY]
    stored = read_suggestion(_provider_config(db_conn, company_id))
    assert stored is not None and stored["company_id"] == "spotify"

    await fetch_custom_company(company_id=company_id)
    assert scored == [company_id], "a later harvest must NOT score it again"
    # Byte-for-byte, ``detected_at`` included: a re-store would move the timestamp even
    # when it lands on the same company.
    assert _provider_config(db_conn, company_id)[pbm.SUGGESTION_KEY] == blob


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


# ======================================================================================
# THE TRIGGER — a board that can never VERIFY, which is the case unit 10 exists for
# ======================================================================================
#
# ``lifeatspotify.com`` returns its whole catalogue in ONE request, so discovery stores it
# ``oracle_kind='none'`` and ``verify_harvest`` answers UNVERIFIED ``no_oracle``
# unconditionally. Gating the comparison on VERIFIED therefore made the entire unit
# unreachable for the ONE case it was written for. Measured on the live row:
# ``tracking_started_at`` NULL, no suggestion, while ``find_published_match`` by hand
# returns ``spotify``, 70 of 79 titles, ratio 0.875, qualifying.
#
# The fix does not widen VERIFIED — it moves the trigger to ``read_untruncated``, a
# strictly weaker predicate that licences nothing destructive. The tests below pin both
# halves: the suggestion is now reachable, AND the close path is exactly where it was.

_SPOTIFY_SHARED = 70      # the measured overlap
_SPOTIFY_CANDIDATE = 79   # distinct normalized OPEN titles on lifeatspotify
_SPOTIFY_PUBLIC = 80      # distinct normalized OPEN titles on lever:spotify
_SPOTIFY_RATIO = 0.875    # 70 / max(79, 80)


def _none_oracle_script(*, paginate: dict | None = None) -> dict:
    """A discovered ``http_json`` recipe whose oracle is ``none`` — the lifeatspotify shape.

    One GET, no pagination, no total anywhere in the payload. ``paginate`` swaps in a
    paging step so the same helper can build the TRUNCATED counter-case.
    """
    steps: list[dict] = [
        {"op": "fetch", "method": "GET",
         "url": "https://api.lifeatspotify.test/wp-json/animal/v1/job/search",
         "headers": {}},
    ]
    if paginate is not None:
        steps.append(paginate)
    steps += [
        {"op": "extract_json_path", "records_path": "result",
         "fields": {"id": "id", "title": "text", "url": "https://x.test/jobs/{id}"}},
        {"op": "dedupe_key", "field": "id"},
        {"op": "assert_unique", "field": "id"},
    ]
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "base_url": "https://x.test",
        "steps": steps,
        "oracle": {"kind": "none"},
    }


def _payload_of(titles) -> dict:
    return {"result": [{"id": str(i), "text": t} for i, t in enumerate(titles)]}


def _patch_http_json(monkeypatch, responder) -> None:
    """Point the leaf task's SSRF-guarded client at ``responder`` (an httpx handler)."""
    import api.tasks.fetch_custom_company as task_mod

    monkeypatch.setattr(
        task_mod, "_recipe_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(responder)),
    )


def _harvest_row(db_conn, company_id: str) -> dict:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT verdict, verdict_reason, records_harvested, cap_hit "
            "FROM {} WHERE company_id = %s ORDER BY started_at DESC"
        ).format(sql.Identifier("company_harvests")),
        (company_id,),
    )
    return dict(cur.fetchone())


# --- the predicate, pure --------------------------------------------------------------


def _evidence(**kw):
    from api.services.harvest_meta import HarvestEvidence

    base = dict(declared_total=None, cap_hit=False, terminated_cleanly=True,
                page_advance_ok=None, pages_fetched=1)
    base.update(kw)
    return HarvestEvidence(**base)


def test_read_untruncated_accepts_the_single_request_whole_catalogue_shape() -> None:
    """The bug, at the level of the one predicate that decides it.

    ``verify_harvest('none', ...)`` returns UNVERIFIED ``no_oracle`` — and MUST keep
    returning it, because a single response holding 79 jobs is indistinguishable from page
    one of a 400-job board. But nothing about that run says the read stopped early: one
    request, one 200, every record in the body mapped. That is what the comparison needs.
    """
    from api.services.harvest_verification import (
        UNVERIFIED, HarvestVerdict, read_untruncated,
    )

    verdict = HarvestVerdict(UNVERIFIED, "no_oracle")
    assert read_untruncated(verdict, _evidence()) is True


@pytest.mark.parametrize(
    "reason, evidence_kw",
    [
        # Every UNVERIFIED reason that IS, or MAY BE, a short read. Each must be refused —
        # comparing a truncated candidate against a whole public board answers a question
        # about a board that does not exist.
        ("cap_hit", {"cap_hit": True, "terminated_cleanly": False}),
        ("page_advance_failed", {"page_advance_ok": False}),
        ("not_terminated_cleanly", {"terminated_cleanly": False}),
        ("count_mismatch", {"declared_total": 400}),
        ("over_harvest", {"declared_total": 40}),
        ("delta_anomaly", {}),
        ("zero_unproven", {}),
    ],
)
def test_read_untruncated_refuses_every_short_read_shape(reason, evidence_kw) -> None:
    """Two independent rails, and the parametrization exercises both.

    ``cap_hit`` / ``page_advance_failed`` / ``not_terminated_cleanly`` are refused on the
    EVIDENCE (they would be refused even carrying a ``no_oracle`` reason — which matters,
    because a ``no_oracle`` verdict carries the DEFAULTS for those fields, so reading them
    off the verdict would silently always pass). The rest are refused on the reason.
    """
    from api.services.harvest_verification import (
        UNVERIFIED, HarvestVerdict, read_untruncated,
    )

    assert read_untruncated(
        HarvestVerdict(UNVERIFIED, reason), _evidence(**evidence_kw)
    ) is False
    # ...and the evidence rail holds even under the one reason that is otherwise allowed.
    if evidence_kw:
        assert read_untruncated(
            HarvestVerdict(UNVERIFIED, "no_oracle"), _evidence(**evidence_kw)
        ) is (evidence_kw.keys() <= {"declared_total"})


def test_read_untruncated_refuses_a_failed_run() -> None:
    """A FAILED run wrote no rows, so the OPEN set in the database is somebody else's.

    The reason is deliberately ``no_oracle`` — the ONE reason that is otherwise comparable —
    so this isolates the FAILED rail instead of passing for free on an unrecognized reason
    string. That matters because the rail is a CONTRACT guard, not a live branch:
    ``verify_harvest`` never returns FAILED today (a gate failure RAISES instead), so at the
    task level the equivalent protection is the ``success and comparable_read`` conjunction.
    The rail exists so the predicate is total over its own input type.
    """
    from api.services.harvest_verification import FAILED, HarvestVerdict, read_untruncated

    assert read_untruncated(HarvestVerdict(FAILED, "no_oracle"), _evidence()) is False


def test_a_cap_hit_alone_disqualifies_even_if_the_client_claims_a_clean_finish() -> None:
    """The cap rail, isolated from the termination rail.

    In every shape the code can currently PRODUCE the two move together —
    ``finalize_harvest`` computes ``terminated_cleanly and not cap_hit``, and the ATS
    clients set ``terminated_cleanly=False`` whenever they stop on a ceiling. So no
    realistic fixture exercises the cap rail on its own, and without this test a mutant
    that deletes it survives.

    They are still two separate claims — "a ceiling stopped us" and "we ended on a short
    page" — and a client that reported both would be a bug whose title set we must still
    refuse, not silently accept. Pinned here so the rail cannot be deleted as dead weight.
    """
    from api.services.harvest_verification import (
        UNVERIFIED, HarvestVerdict, read_untruncated,
    )

    assert read_untruncated(
        HarvestVerdict(UNVERIFIED, "no_oracle"),
        _evidence(cap_hit=True, terminated_cleanly=True),
    ) is False


def test_a_public_company_id_is_never_even_scored(db_conn, monkeypatch) -> None:
    """The latch read carries ``visibility = 'user'``, exactly like the two writes.

    This module has business only with private rows. A public id must stop at the latch
    read, before the fleet-wide comparison and before either write — which both carry their
    own visibility clause, so nothing could land, but "nothing lands" is not the same claim
    as "we never looked".
    """
    _seed_pair(
        db_conn, candidate_titles=_titles("Custom", 40), public_titles=_titles("Public", 40)
    )
    scored: list[str] = []
    real = pbm.find_published_match
    monkeypatch.setattr(
        pbm, "find_published_match",
        lambda conn, cid: (scored.append(cid), real(conn, cid))[1],
    )

    assert suggest_published_board(db_conn, "spotify") is None
    assert scored == [], "a public company id reached the comparison"
    assert _provider_config(db_conn, "spotify") == {}


def test_a_verified_run_is_always_comparable() -> None:
    """The pre-existing trigger is a strict subset of the new one — nothing regressed."""
    from api.services.harvest_verification import VERIFIED, HarvestVerdict, read_untruncated

    assert read_untruncated(
        HarvestVerdict(VERIFIED, "declared_exact"), _evidence(declared_total=79)
    ) is True


def test_no_oracle_still_never_verifies() -> None:
    """**THE GUARDRAIL, pinned.** The unit-10 fix must not have widened VERIFIED by one
    inch, and it did not.

    VERIFIED is what licences the close sweep. Every shape below still answers UNVERIFIED
    ``no_oracle`` — and note WHY, because the reason changed under this test without the
    assertions moving: ``verify_harvest`` is called with no ``recipe``, and no recipe means
    no completeness claim. The history-delta oracle that lets a discovered ``none`` board
    verify is reachable only from the caller that has the stored request to reason about
    (``tasks.fetch_custom_company``, discovered transports only), so every OTHER caller —
    the six public ATS crons, the custom ATS path, and this test — is byte-identical.
    """
    from api.services.custom_baseline import Baseline
    from api.services.harvest_verification import (
        UNVERIFIED, GateResult, verify_harvest,
    )

    gate = GateResult(jobs=[], records_harvested=79, id_dedup_dropped=0)
    for evidence in (
        _evidence(),
        _evidence(declared_total=79),
        _evidence(cap_hit=True, terminated_cleanly=False),
        _evidence(page_advance_ok=False),
        _evidence(terminated_cleanly=False),
    ):
        v = verify_harvest("none", gate, evidence, Baseline(None, 0, 0.5))
        assert (v.verdict, v.reason) == (UNVERIFIED, "no_oracle")


# --- end to end: the real measured Spotify shape --------------------------------------


@pytest.mark.asyncio
async def test_lifeatspotify_reaches_the_suggestion_end_to_end(db_conn, monkeypatch) -> None:
    """**The bug, fixed, at the level the user experiences it.**

    A discovered board that returns its whole catalogue in one request, harvested by the
    real leaf task, produces the Spotify suggestion. Numbers are the measured ones: 70
    shared of 79 candidate titles against 80 on ``lever:spotify``, ratio 0.875.

    The run's VERDICT moved under it and that is fine: with the history-delta oracle a
    single-request board with no page-shaped parameter now reaches VERIFIED instead of
    UNVERIFIED ``no_oracle``. What this test is about — that the comparison is REACHED
    for a whole-catalogue board — is unchanged, and ``read_untruncated`` was always
    true for this shape either way.
    """
    from api.tests.test_fetch_custom_company import _patch_env, _seed_discovered_company

    company_id = "u-lifeatsp01"
    shared = _titles("Shared", _SPOTIFY_SHARED)
    candidate = shared + _titles("OnlyCustom", _SPOTIFY_CANDIDATE - _SPOTIFY_SHARED)
    public = shared + _titles("OnlyPublic", _SPOTIFY_PUBLIC - _SPOTIFY_SHARED)

    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=_none_oracle_script(), oracle_kind="none"
    )
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", public, source_id="lever_api")
    _patch_http_json(
        monkeypatch,
        lambda _req: httpx.Response(200, json=_payload_of(candidate)),
    )

    await fetch_custom_company(company_id=company_id)

    harvest = _harvest_row(db_conn, company_id)
    assert (harvest["verdict"], harvest["verdict_reason"]) == (
        "VERIFIED", "history_delta_ok",
    )
    assert harvest["records_harvested"] == _SPOTIFY_CANDIDATE

    stored = read_suggestion(_provider_config(db_conn, company_id))
    assert stored is not None, (
        "the whole-catalogue board produced no suggestion — unit 10 is unreachable again"
    )
    assert stored["company_id"] == "spotify"
    assert (stored["shared"], stored["candidate_titles"]) == (
        _SPOTIFY_SHARED, _SPOTIFY_CANDIDATE,
    )
    blob = _provider_config(db_conn, company_id)[pbm.SUGGESTION_KEY]
    assert round(blob["shared"] / max(blob["candidate_titles"], blob["matched_titles"]), 3) \
        == _SPOTIFY_RATIO


@pytest.mark.asyncio
async def test_the_unverified_suggestion_run_closes_nothing_and_accrues_no_miss(
    db_conn, monkeypatch
) -> None:
    """**THE CLOSE PATH, PROVEN SAFE — on the very run that now stores a suggestion.**

    Same run, both properties. The six jobs the board used to carry have vanished from
    the payload, are long past the 36h floor, and carry five misses already — maximally
    close-eligible.

    They still do not close, and the branch that stops them moved: this is the board's
    FIRST harvest, so ``first_verified_run`` refuses it. (Before the history-delta
    oracle the refusal came from ``unverified_harvest``, because an ``oracle_kind='none'``
    board could never VERIFY at all. A ``none`` board CAN now close — that is the
    feature — but never on run one, and never before a five-run VERIFIED streak; the full
    ladder is exercised in ``test_history_delta_oracle.py``.)

    Asserted: every prior job is still OPEN, ``consecutive_misses`` is still 5 (this run
    did not even count as a MISS, let alone a close), and ``scrape_runs.closed_jobs`` is
    0 — while the suggestion IS stored, which is the point: the comparison is reached
    WITHOUT reaching anything destructive.
    """
    from api.tests.test_fetch_custom_company import (
        _job_status, _patch_env, _rows, _scrape_runs, _seed_discovered_company,
    )

    company_id = "u-noclose001"
    shared = _titles("Shared", _SPOTIFY_SHARED)
    candidate = shared + _titles("OnlyCustom", _SPOTIFY_CANDIDATE - _SPOTIFY_SHARED)
    public = shared + _titles("OnlyPublic", _SPOTIFY_PUBLIC - _SPOTIFY_SHARED)

    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=_none_oracle_script(), oracle_kind="none"
    )
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", public, source_id="lever_api")

    # Six jobs already OPEN under this board, none of them in today's payload, all last
    # seen 10 days ago and already carrying misses — maximally close-eligible.
    _insert_jobs(db_conn, company_id, [f"Gone Role {i}" for i in range(6)])
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE job_freshness SET last_seen_at = now() - interval '10 days', "
        "consecutive_misses = 5 WHERE source_id = %s",
        (custom(company_id),),
    )
    db_conn.commit()

    _patch_http_json(
        monkeypatch,
        lambda _req: httpx.Response(200, json=_payload_of(candidate)),
    )

    await fetch_custom_company(company_id=company_id)

    # 1. The suggestion landed — the run DID reach the comparison.
    assert read_suggestion(_provider_config(db_conn, company_id)) is not None

    # 2. And reached nothing destructive. Not one of the six vanished jobs closed...
    statuses = _job_status(db_conn, company_id)
    gone = {jid: row for jid, row in statuses.items() if jid.startswith(company_id)}
    assert len(gone) == 6
    assert {row["status"] for row in gone.values()} == {"OPEN"}
    # ...and not one of them was even counted as a miss.
    assert {row["consecutive_misses"] for row in gone.values()} == {5}

    # 3. The verdict ladder refused the close on the first-run gate.
    run = _scrape_runs(db_conn, company_id)[-1]
    assert run["closed_jobs"] == 0
    assert run["guard_reason"] == "first_verified_run"
    assert _rows(db_conn, "company_harvests", company_id)[-1]["verdict"] == "VERIFIED"


@pytest.mark.asyncio
async def test_a_truncated_read_produces_no_suggestion_and_does_not_burn_the_latch(
    db_conn, monkeypatch
) -> None:
    """A genuinely PARTIAL read must not be compared — even when it would score 0.875.

    The board pages, its window cap stops the sweep after page one, and the 70 titles we
    did get are all on ``lever:spotify``'s 80. Scored, that is 70/80 = 0.875 — over the
    bar. It is still the wrong answer, because the real board may be 400 jobs of which we
    saw 70, and this comparison would be a statement about a board that does not exist.

    The second assertion is the one that makes the refusal safe rather than merely strict:
    the once-latch is NOT written, so a later healthy run still gets its comparison. A
    truncated run costs the board nothing; it just does not get to answer.
    """
    from api.tests.test_fetch_custom_company import _patch_env, _seed_discovered_company

    company_id = "u-truncated1"
    shared = _titles("Shared", _SPOTIFY_SHARED)
    public = shared + _titles("OnlyPublic", _SPOTIFY_PUBLIC - _SPOTIFY_SHARED)

    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id,
        script=_none_oracle_script(paginate={
            "op": "paginate_offset", "param": "offset",
            "page_size": _SPOTIFY_SHARED, "max_pages": 5,
            # The furthest offset the API will serve: one full page, then the sweep stops
            # on the cap with no short final page → cap_hit, terminated_cleanly=False.
            "window_cap": _SPOTIFY_SHARED,
        }),
        oracle_kind="none",
    )
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", public, source_id="lever_api")
    _patch_http_json(
        monkeypatch,
        lambda _req: httpx.Response(200, json=_payload_of(shared)),
    )

    await fetch_custom_company(company_id=company_id)

    harvest = _harvest_row(db_conn, company_id)
    assert harvest["cap_hit"] is True, "the fixture must actually produce a capped sweep"
    assert harvest["records_harvested"] == _SPOTIFY_SHARED

    config = _provider_config(db_conn, company_id)
    assert pbm.SUGGESTION_KEY not in config, "a truncated read was compared"
    assert pbm.CHECKED_KEY not in config, (
        "a truncated read burned the once-latch — the board can now never be compared"
    )


@pytest.mark.asyncio
async def test_a_run_that_fails_after_the_flag_is_set_is_not_comparable(
    db_conn, monkeypatch
) -> None:
    """``comparable_read`` is ANDed with ``success``, and this is why.

    The flag is set mid-``_work``, right after the rows land — the earliest honest point,
    since the comparison reads ``job_listings``. But ``_work`` can still fail AFTER that:
    here ``mark_verified`` raises a ``psycopg2.Error``, which the leaf task's narrow
    ``except`` converts to a recorded FAILED run. A FAILED run is not a run whose OPEN set
    we should be drawing conclusions from, so the ``finally`` must not compare it.

    Without the ``success and``, the flag alone would send it straight to the comparison —
    and, worse, BURN THE ONCE-LATCH on a run that failed.
    """
    from api.services import custom_companies_service as task_ccs
    from api.tests.test_fetch_custom_company import _patch_env, _seed_discovered_company

    company_id = "u-flagfail01"
    shared = _titles("Shared", _SPOTIFY_SHARED)
    candidate = shared + _titles("OnlyCustom", _SPOTIFY_CANDIDATE - _SPOTIFY_SHARED)
    public = shared + _titles("OnlyPublic", _SPOTIFY_PUBLIC - _SPOTIFY_SHARED)

    _patch_env(monkeypatch)
    # ``declared_probed`` so the run reaches ``mark_verified`` at all — the injection point
    # has to sit AFTER the flag, and on a ``no_oracle`` board nothing does.
    script = _none_oracle_script()
    script["oracle"] = {"kind": "declared_probed", "total_path": "total"}
    _seed_discovered_company(
        db_conn, company_id, script=script, oracle_kind="declared_probed"
    )
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", public, source_id="lever_api")

    payload = _payload_of(candidate)
    payload["total"] = len(candidate)
    _patch_http_json(monkeypatch, lambda _req: httpx.Response(200, json=payload))

    def _boom(conn, cid, *, set_tracking):
        raise psycopg2.OperationalError("connection died mid-run")

    monkeypatch.setattr(task_ccs, "mark_verified", _boom)

    with pytest.raises(psycopg2.Error):
        await fetch_custom_company(company_id=company_id)

    config = _provider_config(db_conn, company_id)
    assert pbm.SUGGESTION_KEY not in config, "a FAILED run was compared"
    assert pbm.CHECKED_KEY not in config, "a FAILED run burned the once-latch"


@pytest.mark.asyncio
async def test_the_unverified_suggestion_path_still_never_merges(db_conn, monkeypatch) -> None:
    """**DECISION D6 on the newly-reachable path.** Same audit, ``no_oracle`` board.

    ``test_a_merge_is_never_performed`` proves this for the comparison in isolation. This
    proves it for the path that now actually runs in production: the whole leaf task, on a
    board that will never verify, snapshotted around the ``finally`` block that calls it.

    The harvest itself legitimately writes ``job_listings`` (that is what a harvest is), so
    the snapshot is taken with the board's rows ALREADY landed — a second identical run,
    whose only remaining effect can be the suggestion.
    """
    from api.tests.test_fetch_custom_company import _patch_env, _seed_discovered_company

    company_id = "u-nomerge001"
    shared = _titles("Shared", _SPOTIFY_SHARED)
    candidate = shared + _titles("OnlyCustom", _SPOTIFY_CANDIDATE - _SPOTIFY_SHARED)
    public = shared + _titles("OnlyPublic", _SPOTIFY_PUBLIC - _SPOTIFY_SHARED)

    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=_none_oracle_script(), oracle_kind="none"
    )
    _insert_company(db_conn, "spotify", visibility="public", display_name="Spotify")
    _insert_jobs(db_conn, "spotify", public, source_id="lever_api")
    _patch_http_json(
        monkeypatch,
        lambda _req: httpx.Response(200, json=_payload_of(candidate)),
    )

    # Run 1 lands the rows AND (with them) the suggestion. Clear the suggestion + latch so
    # run 2 re-does exactly the comparison, with the job rows already in their final state.
    await fetch_custom_company(company_id=company_id)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET provider_config = '{{}}'::jsonb WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (company_id,),
    )
    db_conn.commit()

    jobs_before, companies_before = _snapshot(db_conn)
    await fetch_custom_company(company_id=company_id)
    jobs_after, companies_after = _snapshot(db_conn)

    assert read_suggestion(_provider_config(db_conn, company_id)) is not None

    # 1. Not one job row written — no row moved to the public company, none re-pointed,
    #    none inserted, none deleted. (last_seen_at lives in job_freshness, not here.)
    assert jobs_after == jobs_before
    # 2. No company INSERTed or DELETEd.
    assert [c["id"] for c in companies_after] == [c["id"] for c in companies_before]
    # 3. The only UPDATE is provider_config, on the private row.
    before_by_id = {c["id"]: c for c in companies_before}
    for after in companies_after:
        changed = {k for k in after if after[k] != before_by_id[after["id"]][k]}
        expected = {"provider_config", "last_success_at"} if after["id"] == company_id else set()
        assert changed <= expected, f"{after['id']} changed {changed}"
        if after["id"] == company_id:
            assert "provider_config" in changed
    # 4. And the public company is untouched in every column, its own config included.
    assert before_by_id["spotify"] == next(c for c in companies_after if c["id"] == "spotify")
