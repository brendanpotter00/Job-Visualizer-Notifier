"""AC-07, AC-09, AC-10, AC-11 — delete/purge, flags, isolation, idempotency
(PLAN.md §5 "AC-07", "AC-09/AC-10/AC-11/AC-12").
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import boards
import httpx
import pytest
from conftest import BASE_URL, db, poll_until, require_reachable

CISCO_URL = boards.CISCO.url
ATLASSIAN_URL = boards.ATLASSIAN.url

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_E2E = _REPO_ROOT / "e2e" / "shared" / "stack" / "env.e2e"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


@contextmanager
def _flagged_backend(port: int, overrides: dict[str, str]):
    """A second, short-lived backend on `port` with `overrides` applied on
    top of env.e2e (PLAN.md AC-09: "Needs a second short-lived backend on
    another port with the flags flipped."). Same jobscraper_e2e database —
    safe, because the flag-off routes never write anything."""
    env = dict(os.environ)
    env.update(_parse_env_file(_ENV_E2E))
    env.pop("INTERNAL_API_KEY", None)
    env["PORT"] = str(port)
    env["SCRAPER_COMPANIES"] = ""
    env.update(overrides)

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "e2e.shared.stack.e2e_app:app",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60.0
        healthy = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
                raise RuntimeError(f"flagged backend on :{port} exited early:\n{out}")
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
                if r.status_code == 200:
                    healthy = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        if not healthy:
            raise RuntimeError(f"flagged backend on :{port} did not become healthy in time")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


class TestDeleteMeansGone:
    """AC-07."""

    @pytest.mark.live
    def test_ac07_delete_purges_everything_and_leaves_state_clean_for_a_fresh_readd(
        self, http, db_conn
    ):
        require_reachable(boards.CISCO)
        baseline_ownerless = db.ownerless_count(BASE_URL)

        resp = http.post("/api/users/companies", json={"url": CISCO_URL})
        assert resp.status_code == 201, resp.text
        company_id = resp.json()["id"]

        # Give it a real harvest so the purge assertion (job_listings == 0) is
        # not vacuous.
        settled = poll_until(
            http, company_id, lambda r: r.get("lastSuccessAt") is not None,
            timeout_s=180.0, what="first harvest completed",
        )
        assert settled["openJobCount"] > 0

        source_id = f"custom:{company_id}"
        assert db.job_listing_count(db_conn, source_id=source_id) > 0, (
            "test setup: expected some job_listings before delete, to make the "
            "purge assertion meaningful"
        )

        del_resp = http.delete(f"/api/users/companies/{company_id}")
        assert del_resp.status_code == 204, del_resp.text

        list_resp = http.get("/api/users/companies")
        assert all(c["id"] != company_id for c in list_resp.json()["companies"]), (
            "AC-07 assertion 3: deleted company must be gone from GET /api/users/companies"
        )

        assert db.company_row(db_conn, company_id) is None, "companies row must be gone"
        assert db.company_script_row(db_conn, company_id) is None, "company_scripts row must be gone"
        user_id = db.user_id_for_email(db_conn, "e2e+add-companies@jvn.test")
        assert db.user_companies_row(db_conn, user_id, company_id) is None, (
            "user_companies row must be gone"
        )
        assert db.job_listing_count(db_conn, source_id=source_id) == 0, (
            "AC-07 assertion 5: every job_listings row under this company's "
            "custom:<id> namespace must be gone"
        )

        # Assertion 6: ownerlessCount delta, not absolute value (PLAN.md §5
        # baseline caution — the dev DB's baseline is NOT guaranteed to be 0).
        after_ownerless = db.ownerless_count(BASE_URL)
        assert after_ownerless == baseline_ownerless, (
            f"AC-07 assertion 6: ownerlessCount must be unchanged by a correct "
            f"purge (baseline={baseline_ownerless}, after={after_ownerless})"
        )

        # Assertion 7: re-adding the same URL immediately starts a FRESH flow.
        readd = http.post("/api/users/companies", json={"url": CISCO_URL})
        assert readd.status_code == 201, (
            f"AC-07 assertion 7: re-adding after a full purge must start a fresh "
            f"add (201), not resolve to a stale row; got {readd.status_code}: {readd.text}"
        )
        new_company_id = readd.json()["id"]
        assert new_company_id != company_id, (
            "AC-07 assertion 7: the re-add must mint a NEW id, not reuse the purged one"
        )


class TestFeatureFlags:
    """AC-09."""

    def test_ac09_sources_flag_off_503s_every_route(self, primary_token: str):
        # No require_reachable: _require_flag() 503s before the router ever
        # touches payload.url, so this never makes a live network call.
        with _flagged_backend(8202, {"CUSTOM_COMPANY_SOURCES_ENABLED": "false"}) as base:
            client = httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {primary_token}"}, timeout=30.0
            )
            r = client.get("/api/users/companies")
            assert r.status_code == 503, f"GET /api/users/companies: {r.status_code} {r.text}"
            r = client.post("/api/users/companies", json={"url": ATLASSIAN_URL})
            assert r.status_code == 503, f"POST /api/users/companies: {r.status_code} {r.text}"
            r = client.delete("/api/users/companies/u-doesnotexist")
            assert r.status_code == 503, f"DELETE /api/users/companies/x: {r.status_code} {r.text}"
            client.close()

    def test_ac09_discovery_flag_off_returns_422_with_no_side_effects(
        self, primary_token: str, db_conn
    ):
        require_reachable(boards.ATLASSIAN)
        with _flagged_backend(
            8202,
            {
                "CUSTOM_COMPANY_SOURCES_ENABLED": "true",
                "CUSTOM_COMPANY_DISCOVERY_ENABLED": "false",
            },
        ) as base:
            client = httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {primary_token}"}, timeout=30.0
            )
            before_user = db.visibility_count(db_conn, "user")
            before_jobs = db.procrastinate_job_count(db_conn, queue_name="custom_discovery")

            r = client.post("/api/users/companies", json={"url": ATLASSIAN_URL})
            assert r.status_code == 422, f"expected 422 unsupported, got {r.status_code}: {r.text}"
            body = r.json()
            assert body.get("reason") in ("unsupported", "no_ats_detected"), body

            after_user = db.visibility_count(db_conn, "user")
            after_jobs = db.procrastinate_job_count(db_conn, queue_name="custom_discovery")
            assert after_user == before_user, "no placeholder row may be created"
            assert after_jobs == before_jobs, (
                "no custom_discovery job may be enqueued — and by extension no "
                "Haiku call is ever made, since that job is the only thing that "
                "invokes the capture pipeline"
            )
            client.close()


class TestOwnershipIsolation:
    """AC-10."""

    def test_ac10_user_b_cannot_see_read_or_delete_user_as_company(self, http, other_http):
        require_reachable(boards.CISCO)
        resp = http.post("/api/users/companies", json={"url": CISCO_URL})
        assert resp.status_code == 201, resp.text
        company_id = resp.json()["id"]

        b_list = other_http.get("/api/users/companies")
        assert b_list.status_code == 200
        assert all(c["id"] != company_id for c in b_list.json()["companies"]), (
            "AC-10: user B's list must omit user A's company"
        )

        b_jobs = other_http.get(f"/api/users/companies/{company_id}/jobs")
        assert b_jobs.status_code == 403, (
            f"AC-10: user B reading A's jobs must 403, got {b_jobs.status_code}"
        )

        b_delete = other_http.delete(f"/api/users/companies/{company_id}")
        assert b_delete.status_code == 404, (
            f"AC-10: user B deleting A's company must 404 (not reveal existence "
            f"via 403), got {b_delete.status_code}"
        )

        a_list = http.get("/api/users/companies")
        assert any(c["id"] == company_id for c in a_list.json()["companies"]), (
            "AC-10: A's row must still exist after B's failed delete attempt"
        )


class TestIdempotentReadd:
    """AC-11 — a typo must never cost an LLM call."""

    @pytest.mark.live
    def test_ac11_readding_a_discovered_board_is_free_and_idempotent(self, http, db_conn):
        require_reachable(boards.ATLASSIAN)
        resp = http.post("/api/users/companies", json={"url": ATLASSIAN_URL})
        assert resp.status_code == 202, resp.text
        company_id = resp.json()["id"]

        def _tracking(row: dict) -> bool:
            # Every TERMINAL outcome, not just the two we hope for. ``partial`` is
            # terminal too (``discovery/progress.py`` ``_OUTCOMES``); leaving it out
            # turns a settled-but-partial board into a 240s poll and then an assertion
            # that blames a hang instead of naming the outcome we actually got.
            return (row.get("discovery") or {}).get("outcome") in (
                "tracking", "partial", "refused",
            )

        settled = poll_until(http, company_id, _tracking, timeout_s=240.0, what="discovery settled")
        assert settled["discovery"]["outcome"] == "tracking"

        before_user = db.visibility_count(db_conn, "user")
        before_jobs = db.procrastinate_job_count(db_conn, queue_name="custom_discovery")

        readd = http.post("/api/users/companies", json={"url": ATLASSIAN_URL})
        assert readd.status_code == 200, (
            f"AC-11: re-adding an already-discovered board must return 200 with "
            f"the existing row, got {readd.status_code}: {readd.text}"
        )
        assert readd.json()["id"] == company_id

        after_user = db.visibility_count(db_conn, "user")
        after_jobs = db.procrastinate_job_count(db_conn, queue_name="custom_discovery")
        assert after_user == before_user, "AC-11: no second companies row"
        assert after_jobs == before_jobs, (
            "AC-11: no second custom_discovery job — the whole point being that a "
            "typo / accidental double-submit must never cost another LLM call"
        )


# A hostname nothing can resolve. Every add below is refused by the SSRF/DNS guard
# before a single byte leaves the machine, so this whole case is FAST: no board, no
# network, no LLM — only the limits are under test.
_UNRESOLVABLE = "https://no-such-board-{n}.invalid/careers"

PRIMARY_EMAIL = "e2e+add-companies@jvn.test"


class TestPerUserAddLimits:
    """AC-14 — the monthly cap and the burst limiter, on the REAL endpoint.

    A bearer token, `httpx`, and nothing else: the same shape as a token copied out
    of DevTools and replayed with curl. Nothing here can be satisfied by a disabled
    submit button, which is the whole reason the case exists.

    Both limits get a short-lived backend on :8202 with their own values, exactly the
    way AC-09 does for the feature flags. The main stack runs with the cap OFF
    (`env.e2e`) because `company_add_attempts` is append-only and its count therefore
    survives every `reset_user.sweep` and every re-run of this suite.
    """

    def test_ac14_the_monthly_cap_refuses_the_next_add_and_the_counter_says_so(
        self, primary_token: str, db_conn
    ):
        user_id = db.user_id_for_email(db_conn, PRIMARY_EMAIL)
        assert user_id, f"expected a users row for {PRIMARY_EMAIL}"
        # Place the user at a known count. Nothing in the product can do this — the
        # audit is append-only on purpose — so the fixture reaches past the API.
        db.clear_add_attempts(db_conn, user_id=user_id)

        with _flagged_backend(
            8202,
            {
                "CUSTOM_COMPANY_SOURCES_ENABLED": "true",
                "CUSTOM_COMPANY_DISCOVERY_ENABLED": "false",
                "CUSTOM_COMPANY_MONTHLY_ADD_LIMIT": "3",
                "USER_COMPANY_ADD_RATE_LIMIT_MAX": "100",
            },
        ) as base:
            client = httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {primary_token}"}, timeout=30.0
            )
            try:
                before_user_rows = db.visibility_count(db_conn, "user")

                # A URL WE COULD NOT READ COSTS NOTHING, and that is the half of this
                # case that changed. These `.invalid` hosts are refused by the DNS
                # guard before a byte leaves the machine — no page read, no board
                # judged, nothing enqueued — so the endpoint records no attempt and
                # the counter does not move.
                #
                # It used to assert the opposite ("three refused adds still spend the
                # month"). That was defensible while the Add Companies page previewed
                # every URL through `/api/companies/resolve` first, which charges
                # nothing: a URL only reached THIS endpoint once it had already been
                # resolved. The preview is gone — one press adds the company — so every
                # typo lands here, and charging 1/20 of somebody's month for a mistyped
                # scheme is a fine for a typo, not a cap on URLs entered.
                for i in range(3):
                    r = client.post("/api/users/companies", json={"url": _UNRESOLVABLE.format(n=i)})
                    assert r.status_code == 422, f"add {i}: {r.status_code} {r.text}"
                    assert r.json().get("reason") != "monthly_limit_reached", (
                        f"add {i} must be refused for the URL, not the cap: {r.text}"
                    )

                free = client.get("/api/users/companies").json()["quota"]
                assert free["used"] == 0, (
                    f"a URL we never read must spend no slot: {free}"
                )

                # Now the cap itself. The rows are SEEDED rather than spent, because
                # after the change above there is no cheap way to spend a slot through
                # the API — every real one costs a live board, a harvest or an LLM call.
                # The audit is append-only by design, so this reaches past the API the
                # same way `clear_add_attempts` above does.
                db.seed_add_attempts(db_conn, user_id=user_id, n=3)

                fourth = client.post("/api/users/companies", json={"url": _UNRESOLVABLE.format(n=3)})
                assert fourth.status_code == 422, f"{fourth.status_code} {fourth.text}"
                assert fourth.json()["reason"] == "monthly_limit_reached", fourth.text

                # The counter the Add Companies page renders, from the real endpoint.
                quota = client.get("/api/users/companies").json()["quota"]
                assert quota["used"] == 3, quota
                assert quota["limit"] == 3, quota
                assert quota["resetsAt"], quota

                assert db.visibility_count(db_conn, "user") == before_user_rows, (
                    "a refused add must create no company row"
                )
            finally:
                client.close()

        db.clear_add_attempts(db_conn, user_id=user_id)

    def test_ac14_the_burst_limiter_refuses_and_says_how_long_to_wait_in_the_body(
        self, primary_token: str, db_conn
    ):
        """The wait time must be in the BODY. `api/users.ts` forwards through
        `forwardResponse`, which copies status + body only, so a `Retry-After` header
        never reaches the browser — the same reason `X-Next-Cursor` needs its own
        explicit line in that proxy."""
        user_id = db.user_id_for_email(db_conn, PRIMARY_EMAIL)
        assert user_id
        db.clear_add_attempts(db_conn, user_id=user_id)

        with _flagged_backend(
            8202,
            {
                "CUSTOM_COMPANY_SOURCES_ENABLED": "true",
                "CUSTOM_COMPANY_DISCOVERY_ENABLED": "false",
                "CUSTOM_COMPANY_MONTHLY_ADD_LIMIT": "0",
                "USER_COMPANY_ADD_RATE_LIMIT_MAX": "2",
            },
        ) as base:
            client = httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {primary_token}"}, timeout=30.0
            )
            try:
                codes = [
                    client.post(
                        "/api/users/companies", json={"url": _UNRESOLVABLE.format(n=i)}
                    )
                    for i in range(3)
                ]
                assert [c.status_code for c in codes[:2]] == [422, 422], (
                    [c.status_code for c in codes], codes[0].text
                )
                assert codes[2].status_code == 429, f"{codes[2].status_code} {codes[2].text}"

                detail = codes[2].json()["detail"]
                assert "seconds" in detail and any(ch.isdigit() for ch in detail), detail
                # The header is still sent, for direct API callers like this one.
                assert int(codes[2].headers["retry-after"]) >= 1
            finally:
                client.close()

        db.clear_add_attempts(db_conn, user_id=user_id)

    def test_ac14_the_main_stack_reports_an_uncapped_quota(self, http):
        """The envelope is wired end to end even with the cap switched off — `limit: 0`
        is what tells the UI to render no counter at all."""
        quota = http.get("/api/users/companies").json()["quota"]
        assert quota["limit"] == 0, quota
        assert quota["used"] >= 0, quota
