"""AC-01, AC-02, AC-12 — the careers-host dedupe and its escape hatch
(PLAN.md §5 "AC-01/AC-02", "AC-09/AC-10/AC-11/AC-12").

AC-01 / AC-02: a board we already publish (Microsoft, Amazon — both
`ats='script'`) resolves to `already_public` and creates NOTHING. This is the
exact bug the owner hit (PLAN.md §11.1) — the careers-host match landed while
the plan was being written, so these assert INTENDED behaviour and are
expected green, not a snapshot of a bug.

AC-12: `trackAnyway: true` on the same URL skips the dedupe and DOES create a
private copy — via the SAME one-time discovery pipeline AC-04/05/06 use (a
script-scraped board has no ATS candidate, so `trackAnyway` routes it to
discovery, not a static clone of the public recipe). That also gives AC-01's
assertion #8 ("owned is None" guard) a private row to re-resolve against.
"""

from __future__ import annotations

import time

import boards
import pytest
from conftest import db, require_reachable

MICROSOFT_URL = boards.MICROSOFT.url
AMAZON_URL = boards.AMAZON.url
PRIMARY_EMAIL = "e2e+add-companies@jvn.test"


# Every terminal discovery outcome. ``running`` is the ONLY non-terminal one
# (``discovery/progress.py`` ``_OUTCOMES``), and ``partial`` — a board we can read but
# not the whole of — is as settled as ``tracking`` is. Omitting it made a perfectly
# ordinary Microsoft result poll for the full 240s and then report a hang that never
# happened, which is a harness bug masquerading as a product one.
_SETTLED_OUTCOMES = ("tracking", "partial", "refused")


def _poll_until_settled(http, company_id: str, *, timeout_s: int = 240, interval_s: float = 3.0):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        resp = http.get("/api/users/companies")
        resp.raise_for_status()
        for c in resp.json()["companies"]:
            if c["id"] == company_id:
                last = c
                discovery = c.get("discovery") or {}
                if discovery.get("outcome") in _SETTLED_OUTCOMES:
                    return c
        time.sleep(interval_s)
    raise AssertionError(
        f"company {company_id} did not settle (outcome in {sorted(_SETTLED_OUTCOMES)}) "
        f"within {timeout_s}s; last observed row: {last}"
    )


def _assert_already_public(http, db_conn, url: str, expected_company_id: str, expected_display_name: str):
    before_user = db.visibility_count(db_conn, "user")
    before_attempts = db.add_attempts_count(db_conn)
    before_discovery_jobs = db.procrastinate_job_count(db_conn, queue_name="custom_discovery")

    resp = http.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 200, (
        f'expected 200 already_public for {url!r}, got {resp.status_code}: {resp.text}'
    )
    body = resp.json()
    assert body.get("status") == "already_public", (
        f"expected status=already_public for a board we publish, got: {body}"
    )
    assert body["companyId"] == expected_company_id
    assert body["displayName"] == expected_display_name
    assert body["finalUrl"]

    after_user = db.visibility_count(db_conn, "user")
    assert after_user == before_user, (
        "AC-01/02 assertion 2: already_public must create NO new companies row "
        f"(visibility='user' count was {before_user}, now {after_user})"
    )

    after_attempts = db.add_attempts_count(db_conn)
    assert after_attempts == before_attempts + 1, (
        "AC-01/02 assertion 5: company_add_attempts must gain EXACTLY one row "
        f"(was {before_attempts}, now {after_attempts})"
    )

    after_discovery_jobs = db.procrastinate_job_count(db_conn, queue_name="custom_discovery")
    assert after_discovery_jobs == before_discovery_jobs, (
        "AC-01/02 assertion 4: no custom_discovery job may be created by an "
        "already_public resolution"
    )

    user_id = db.user_id_for_email(db_conn, PRIMARY_EMAIL)
    latest = db.latest_add_attempt(db_conn, user_id=user_id)
    assert latest is not None
    assert latest["outcome"] == "already_public"
    assert latest["company_id"] == expected_company_id
    assert latest["resolved_ats"] == "script", (
        "AC-01/02 assertion 5: resolved_ats must record the sentinel 'script' "
        f"— the audit's record of which half of the dedupe answered, got {latest['resolved_ats']!r}"
    )


class TestAlreadyPublicMicrosoft:
    def test_ac01_microsoft_resolves_to_already_public_and_creates_nothing(self, http, db_conn):
        require_reachable(boards.MICROSOFT)
        _assert_already_public(http, db_conn, MICROSOFT_URL, "microsoft", "Microsoft")


class TestAlreadyPublicAmazon:
    def test_ac02_amazon_resolves_to_already_public_and_creates_nothing(self, http, db_conn):
        require_reachable(boards.AMAZON)
        _assert_already_public(http, db_conn, AMAZON_URL, "amazon", "Amazon")


class TestTrackAnywayEscapeHatch:
    """AC-12: the escape hatch survives the dedupe, and (AC-01 assertion #8)
    a re-add of that same URL afterwards resolves to the caller's OWN private
    row instead of the public notice."""

    @pytest.mark.live
    def test_ac12_track_anyway_creates_private_copy_via_discovery(self, http, db_conn):
        require_reachable(boards.MICROSOFT)
        before_user = db.visibility_count(db_conn, "user")

        resp = http.post(
            "/api/users/companies", json={"url": MICROSOFT_URL, "trackAnyway": True}
        )
        assert resp.status_code == 202, (
            f"AC-12: trackAnyway on a script board (no ATS candidate) must route "
            f"to one-time discovery — expected 202, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["status"] == "discovery_pending"
        company_id = body["id"]

        after_user = db.visibility_count(db_conn, "user")
        assert after_user == before_user + 1, (
            "AC-12: a provisional private row must exist immediately"
        )

        settled = _poll_until_settled(http, company_id)
        outcome = settled["discovery"]["outcome"]
        assert outcome == "tracking", (
            f"AC-12: discovery against Microsoft's own careers page was expected to "
            f"find a readable feed (measured reachable/trackable in PLAN.md §6 — "
            f"'all six were measured tracking'); got outcome={outcome!r}. If this is "
            f"a genuine refusal, it is a real FAIL for a board on the six-board list, "
            f"not a BLOCKED — Microsoft's site may have changed."
        )

        row = db.company_row(db_conn, company_id)
        assert row is not None
        assert row["visibility"] == "user"
        assert row["ats"] != "script", (
            "AC-12: the private copy must be its OWN discovered board, not a clone "
            "of the public microsoft row's ats='script' sentinel"
        )

        # AC-01 assertion #8: re-adding the SAME url now (no trackAnyway) must
        # resolve to THIS private row, not the public already_public notice —
        # the `owned is None` guard.
        resp2 = http.post("/api/users/companies", json={"url": MICROSOFT_URL})
        assert resp2.status_code == 200, resp2.text
        body2 = resp2.json()
        assert body2.get("status") != "already_public", (
            "AC-01 assertion 8: a caller who already owns a private copy must get "
            f"their own row back, not the already_public notice; got: {body2}"
        )
        assert body2["id"] == company_id, (
            "AC-01 assertion 8: the re-add must resolve to the SAME private row "
            f"the caller already owns (expected {company_id!r}, got {body2.get('id')!r})"
        )
