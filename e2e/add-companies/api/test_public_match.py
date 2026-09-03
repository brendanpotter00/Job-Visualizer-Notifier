"""AC-06 / AC-06a — the title-overlap suggestion, and the no-merge guarantee
(PLAN.md §5 "AC-06", §11.2).

AC-06 shipped RED when PLAN.md was written: `suggest_published_board` only
ran when `graduated_this_run` was true (`tasks/fetch_custom_company.py`),
which required a VERIFIED harvest — and a whole-board-in-one-request board
(Spotify's own site) gets `oracle_kind='none'`, so `verify_harvest` returned
`UNVERIFIED, "no_oracle"` unconditionally and the board could never graduate.
The matcher itself was always correct (measured off the dev DB's real
lifeatspotify row: `spotify`, 70 shared of 79 candidate / 80 matched,
ratio=0.875) — only the TRIGGER was wrong.

A sibling agent's fix landed WHILE this suite was being implemented (verified
live: `fetch_custom_company.py`'s trigger is now `if success and
comparable_read`, not `graduated_this_run`/VERIFIED-only — a "comparable"
read is the first UNTRUNCATED harvest, which a whole-board-in-one-request
capture satisfies on its first run) — so this now asserts INTENDED behaviour
against a codebase where that behaviour is ALSO the current behaviour. Kept
exactly as originally specified rather than softened after the fact (PLAN.md:
"Do not weaken it to match current behaviour" — the point holds whichever
direction the drift goes): if the trigger ever regresses, this must go red
again, not quietly stop checking it.

AC-06a exercises the SAME matcher hermetically — no network, no browser, no
LLM — by seeding rows directly and calling the production functions
(`api.services.published_board_match`) against the real e2e DB connection.
This is the one case that keeps the no-merge guarantee under test on days
AC-06 is red (which, per §11.2, is every day until the fix lands).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import boards
import pytest
from conftest import db, poll_until, require_reachable

# Imported directly — same import root e2e_app.py uses (src/backend on
# sys.path via conftest.py) — so AC-06a exercises the REAL production
# matcher, not a reimplementation of it.
from api.services.published_board_match import (  # noqa: E402
    MIN_SHARED_TITLES,
    MIN_TITLE_SET,
    OVERLAP_THRESHOLD,
    find_published_match,
    suggest_published_board,
)

SPOTIFY_URL = boards.SPOTIFY.url
TERMINAL = {"done", "failed"}


def _first_scan_settled(row: dict) -> bool:
    discovery = row.get("discovery") or {}
    for step in discovery.get("steps") or []:
        if step["key"] == "first_scan" and step["status"] in TERMINAL:
            return True
    return False


def _spotify_open_titles_snapshot(conn) -> tuple[int, list[str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT title FROM job_listings "
            "WHERE company = 'spotify' AND status = 'OPEN' ORDER BY title"
        )
        titles = [r["title"] for r in cur.fetchall()]
    return len(titles), titles


class TestPublicBoardMatchLive:
    """AC-06 — shipped RED per PLAN.md §11.2; the trigger fix landed mid-build
    (see module docstring). Asserts intended behaviour either way."""

    @pytest.mark.live
    def test_ac06_spotify_discovery_suggests_the_public_spotify_board(self, http, db_conn):
        require_reachable(boards.SPOTIFY)
        before_count, before_titles = _spotify_open_titles_snapshot(db_conn)

        # The company-name dedupe (AC-13) now answers this URL FIRST — `lifeatspotify`
        # contains `spotify` and we publish Spotify, so a plain add returns 200
        # `already_public` and spends nothing. That is intended and is what AC-13
        # asserts. To have a discovered board for the title-overlap matcher to run
        # against, this case takes the same way out a user would: the "This isn't the
        # same company" correction, which is `trackAnyway` on the wire.
        first = http.post("/api/users/companies", json={"url": SPOTIFY_URL})
        assert first.status_code == 200, first.text
        assert first.json().get("status") == "already_public", (
            "AC-06 precondition: the name dedupe should answer lifeatspotify.com "
            f"before any discovery; got {first.json()}"
        )

        resp = http.post(
            "/api/users/companies", json={"url": SPOTIFY_URL, "trackAnyway": True}
        )
        assert resp.status_code == 202, resp.text
        company_id = resp.json()["id"]

        settled = poll_until(
            http, company_id, _first_scan_settled, timeout_s=240.0,
            what="first harvest settled",
        )
        assert settled["openJobCount"] > 0, "expected a non-empty first harvest"

        row = db.company_row(db_conn, company_id)
        provider_config = row["provider_config"] or {}
        public_match = provider_config.get("public_match")

        assert public_match is not None, (
            "AC-06: expected a 'public_match' suggestion in provider_config after "
            "Spotify's first harvest. This is the PLAN.md §11.2 regression: if "
            "suggest_published_board is gated on graduated_this_run (first VERIFIED "
            "harvest) rather than 'first comparable (untruncated) successful harvest', "
            "a whole-board-in-one-request capture (oracle_kind='none') can never "
            "graduate and the matcher never runs — even though the matcher itself is "
            "correct (see AC-06a, which proves it hermetically). Do not weaken this "
            f"assertion to match a regressed trigger. provider_config keys observed: "
            f"{sorted(provider_config.keys())}"
        )

        assert public_match["company_id"] == "spotify", (
            f"expected the suggestion to name 'spotify', got {public_match['company_id']!r}"
        )
        shared = public_match["shared"]
        candidate_titles = public_match["candidate_titles"]
        matched_titles = public_match.get("matched_titles", candidate_titles)
        ratio = shared / max(candidate_titles, matched_titles)
        assert shared >= MIN_SHARED_TITLES, f"expected shared >= {MIN_SHARED_TITLES}, got {shared}"
        assert ratio >= OVERLAP_THRESHOLD, f"expected ratio >= {OVERLAP_THRESHOLD}, got {ratio:.3f}"

        # Assertion 3: the PUBLIC spotify row's job_listings are byte-identical
        # before and after — nothing merged, nothing written to the public side.
        after_count, after_titles = _spotify_open_titles_snapshot(db_conn)
        assert after_count == before_count and after_titles == before_titles, (
            "the public spotify company's OPEN job_listings must be unchanged by "
            f"this discovery (before={before_count} titles, after={after_count})"
        )

        # Assertion 4: the new (private) company's own identity is untouched —
        # nothing was merged INTO it either.
        assert row["visibility"] == "user"
        assert row["ats"] != "script"
        user_id = db.user_id_for_email(db_conn, "e2e+add-companies@jvn.test")
        uc = db.user_companies_row(db_conn, user_id, company_id)
        assert uc is not None, "the caller must still own their own discovered row"


class TestPublicBoardMatchHermetic:
    """AC-06a — the same guarantee, deterministic and offline (PLAN.md §5)."""

    def test_ac06a_copy_of_spotify_titles_qualifies(self, db_conn):
        _, spotify_titles = _spotify_open_titles_snapshot(db_conn)
        assert len(spotify_titles) >= MIN_TITLE_SET, (
            f"fixture precondition: the public spotify row needs >={MIN_TITLE_SET} "
            f"distinct OPEN titles to exercise the matcher; found {len(spotify_titles)}"
        )

        fixture_id = f"u-e2ehermetic{uuid.uuid4().hex[:8]}"
        _seed_private_company_with_titles(db_conn, fixture_id, spotify_titles)
        try:
            match = find_published_match(db_conn, fixture_id)
            assert match is not None, (
                "AC-06a: a private board carrying an exact copy of Spotify's OPEN "
                "title set must qualify against find_published_match — the matcher "
                "is what AC-06 (live) is red for TRIGGERING, not for computing"
            )
            assert match.company_id == "spotify"
            assert match.shared >= MIN_SHARED_TITLES
            assert match.ratio >= OVERLAP_THRESHOLD

            stored = suggest_published_board(db_conn, fixture_id)
            assert stored is not None
            row = db.company_row(db_conn, fixture_id)
            public_match = (row["provider_config"] or {}).get("public_match")
            assert public_match is not None, "suggest_published_board must store the suggestion"
            assert public_match["company_id"] == "spotify"

            # The only write: no job_listings, no identity/visibility change.
            row_after = db.company_row(db_conn, fixture_id)
            assert row_after["visibility"] == "user"
            assert row_after["ats"] == "discovered"
        finally:
            _delete_fixture_company(db_conn, fixture_id)

    def test_ac06a_25_of_1742_subset_does_not_qualify(self, db_conn):
        """The documented false-positive class (PLAN.md §5, published_board_match.py
        docstring): a 25-title board that is a SUBSET of a 1,742-title parent
        scores 1.00 under shared/min but 0.0144 under shared/max — this module
        uses shared/max, so it must NOT qualify."""
        parent_id = f"zz-e2ehermetic-parent-{uuid.uuid4().hex[:8]}"
        child_id = f"u-e2ehermetic{uuid.uuid4().hex[:8]}"
        parent_titles = [f"Fixture Parent Role {i:04d}" for i in range(1742)]
        child_titles = parent_titles[:25]

        _seed_public_company_with_titles(db_conn, parent_id, parent_titles)
        _seed_private_company_with_titles(db_conn, child_id, child_titles)
        try:
            match = find_published_match(db_conn, child_id)
            assert match is None, (
                f"AC-06a: a 25-of-1,742 SUBSET must not qualify (shared/max ratio "
                f"~0.0144) — got a match: {match}"
            )
        finally:
            _delete_fixture_company(db_conn, child_id)
            _delete_fixture_company(db_conn, parent_id)


def _seed_private_company_with_titles(conn, company_id: str, titles: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (id, display_name, ats, board_token, visibility,
                                    enabled, health_state, provider_config)
            VALUES (%s, %s, 'discovered', %s, 'user', false, 'unverified', '{}'::jsonb)
            """,
            (company_id, f"E2E hermetic fixture {company_id}", company_id),
        )
        source_id = f"custom:{company_id}"
        now = datetime.now(timezone.utc)
        for i, title in enumerate(titles):
            cur.execute(
                """
                INSERT INTO job_listings (id, title, company, url, source_id, status,
                                           created_at, first_seen_at)
                VALUES (%s, %s, %s, %s, %s, 'OPEN', %s, %s)
                """,
                (
                    f"{company_id}-{i}",
                    title,
                    company_id,
                    f"https://example.test/{company_id}/{i}",
                    source_id,
                    now,
                    now,
                ),
            )
    conn.commit()


def _seed_public_company_with_titles(conn, company_id: str, titles: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (id, display_name, ats, board_token, visibility,
                                    enabled, provider_config)
            VALUES (%s, %s, 'greenhouse', %s, 'public', true, '{}'::jsonb)
            """,
            (company_id, f"E2E hermetic parent fixture {company_id}", company_id),
        )
        now = datetime.now(timezone.utc)
        for i, title in enumerate(titles):
            cur.execute(
                """
                INSERT INTO job_listings (id, title, company, url, source_id, status,
                                           created_at, first_seen_at)
                VALUES (%s, %s, %s, %s, 'greenhouse_api', 'OPEN', %s, %s)
                """,
                (
                    f"{company_id}-{i}",
                    title,
                    company_id,
                    f"https://example.test/{company_id}/{i}",
                    now,
                    now,
                ),
            )
    conn.commit()


def _delete_fixture_company(conn, company_id: str) -> None:
    """Direct SQL, deliberately — this is a unit-fixture row this test minted
    out of thin air (no ownership, no script, no harvest), not a real
    user-added company. `remove_owned_company` cannot even reach the public
    fixture (no owner exists for a visibility='public' row); the delete order
    mirrors it anyway for hygiene."""
    with conn.cursor() as cur:
        source_id = f"custom:{company_id}"
        cur.execute("DELETE FROM job_listings WHERE source_id = %s", (source_id,))
        cur.execute("DELETE FROM job_listings WHERE company = %s", (company_id,))
        cur.execute("DELETE FROM user_companies WHERE company_id = %s", (company_id,))
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
    conn.commit()
