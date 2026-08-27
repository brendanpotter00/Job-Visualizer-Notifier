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
            return (row.get("discovery") or {}).get("outcome") in ("tracking", "refused")

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
