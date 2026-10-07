"""Internal Launch Radar routes (``/api/internal/launch-radar/*``), the loop's API.

Driven through a TestClient app that mounts the real router behind the real
``require_internal_key`` middleware (the routes' ONLY gate), with ``get_db``
pointed at the per-module test schema. No Parallel SDK is involved: the backend
never calls Parallel; it only keeps the ledger the loop reserves against.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from api.auth.internal_key import require_internal_key
from api.config import settings
from api.dependencies import get_db
from api.routers import internal_launch_radar
from api.services import launch_radar as svc

from .test_launch_radar_service import (  # noqa: F401  (autouse isolation fixture)
    _card,
    _insert_company,
    _launch_radar_isolation,
    make_payload,
    stored_payload,
)

BASE = "/api/internal/launch-radar"
RUN = "run-0001"
PR_URL = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/412"


@pytest.fixture(scope="module")
def lr_app(db_conn) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(require_internal_key)
    app.include_router(internal_launch_radar.router, prefix=BASE)

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("OK")

    def _override_get_db() -> Iterator[Any]:
        yield db_conn

    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.fixture
def api(lr_app) -> Iterator[TestClient]:
    # Unit tests run with the gate OPEN (key unset), like local dev; the auth
    # class below closes it explicitly.
    prev = settings.internal_api_key
    settings.internal_api_key = None
    try:
        yield TestClient(lr_app)
    finally:
        settings.internal_api_key = prev


def _start(api: TestClient, run_uuid: str = RUN, budget: float = 1.0) -> dict[str, Any]:
    resp = api.post(f"{BASE}/runs", json={"run_uuid": run_uuid, "host": "laptop", "budget_usd": budget})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _reserve(api: TestClient, est: float, *, run_uuid: str = RUN, accrued: bool = False):
    return api.post(
        f"{BASE}/runs/{run_uuid}/reserve",
        json={"step": "findall.create", "est_usd": est, "domain": "a.ai", "accrued": accrued},
    )


def _post_card(api: TestClient, payload: dict[str, Any] | None = None, run_uuid: str = RUN):
    return api.post(f"{BASE}/cards", json={"run_uuid": run_uuid, "payload": payload or make_payload()})


class TestInternalKeyGate:
    def test_without_key_401_when_configured(self, lr_app) -> None:
        prev = settings.internal_api_key
        settings.internal_api_key = "s3cret-test-key"
        try:
            api = TestClient(lr_app)
            for method, path in (
                ("get", "/monitors"),
                ("get", "/seen"),
                ("get", "/pr-candidates"),
                ("post", "/runs"),
                ("post", "/cards"),
                ("get", "/cards?missing_talent=true"),
                ("put", "/cards/1/payload"),
            ):
                resp = getattr(api, method)(f"{BASE}{path}")
                assert resp.status_code == 401, path
            bad = api.get(f"{BASE}/monitors", headers={"X-Internal-Key": "wrong"})
            assert bad.status_code == 401
            ok = api.get(f"{BASE}/monitors", headers={"X-Internal-Key": "s3cret-test-key"})
            assert ok.status_code == 200
            # Railway's healthcheck stays exempt.
            assert api.get("/health").status_code == 200
        finally:
            settings.internal_api_key = prev


class TestRuns:
    def test_start_is_201_and_idempotent(self, api) -> None:
        first = _start(api)
        assert first == {
            "run_id": first["run_id"],
            "run_uuid": RUN,
            "budget_usd": 1.0,
            "run_spend_usd": 0.0,
            "total_spend_usd": 0.0,
            "cap_usd": 5.0,
            "remaining_usd": 5.0,
            "monitors": [],
        }
        assert _start(api)["run_id"] == first["run_id"]

    @pytest.mark.parametrize(
        "body",
        [
            {"run_uuid": "short", "budget_usd": 1.0},
            {"run_uuid": "bad uuid with spaces", "budget_usd": 1.0},
            {"run_uuid": RUN, "budget_usd": 0},
            {"run_uuid": RUN, "budget_usd": 5.01},
            {"run_uuid": RUN, "budget_usd": 1.0, "extra": True},
            {"run_uuid": RUN, "budget_usd": 1.0, "host": "h" * 65},
        ],
    )
    def test_start_validation_422(self, api, body) -> None:
        assert api.post(f"{BASE}/runs", json=body).status_code == 422

    def test_reserve_ok_then_run_budget_402(self, api) -> None:
        _start(api, budget=0.2)
        ok = _reserve(api, 0.15)
        assert ok.status_code == 200
        assert ok.json() == {
            "reserved_usd": 0.15,
            "run_spend_usd": 0.15,
            "total_spend_usd": 0.15,
            "cap_usd": 5.0,
            "over_cap": False,
        }
        refused = _reserve(api, 0.1)
        assert refused.status_code == 402
        assert refused.json() == {
            "detail": {
                "reason": "run_budget",
                "run_spend_usd": 0.15,
                "total_spend_usd": 0.15,
                "cap_usd": 5.0,
            }
        }

    def test_cap_402_and_accrued_past_cap(self, api) -> None:
        settings.launch_radar_spend_cap_usd = 0.3
        _start(api, budget=1.0)
        assert _reserve(api, 0.25).status_code == 200
        refused = _reserve(api, 0.1)
        assert refused.status_code == 402
        assert refused.json()["detail"]["reason"] == "cap"
        accrued = _reserve(api, 0.1, accrued=True)
        assert accrued.status_code == 200
        assert accrued.json()["over_cap"] is True
        assert accrued.json()["total_spend_usd"] == 0.35
        # The next run sees the overspend as negative headroom.
        assert _start(api, "run-0002")["remaining_usd"] == -0.05

    def test_reserve_unknown_run_404_and_finished_run_409(self, api) -> None:
        assert _reserve(api, 0.1, run_uuid="run-missing").status_code == 404
        _start(api)
        api.post(f"{BASE}/runs/{RUN}/finish", json={"status": "ok", "events_read": 0, "cards_posted": 0})
        assert _reserve(api, 0.1).status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"step": "", "est_usd": 0.1},
            {"step": "x" * 65, "est_usd": 0.1},
            {"step": "a", "est_usd": 0},
            {"step": "a", "est_usd": 1.01},
            {"step": "a", "est_usd": 0.1, "bogus": 1},
        ],
    )
    def test_reserve_validation_422(self, api, body) -> None:
        _start(api)
        assert api.post(f"{BASE}/runs/{RUN}/reserve", json=body).status_code == 422

    def test_finish(self, api) -> None:
        _start(api)
        _reserve(api, 0.33)
        body = {"status": "ok", "events_read": 12, "cards_posted": 0, "notes": "done"}
        resp = api.post(f"{BASE}/runs/{RUN}/finish", json=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["run_spend_usd"] == 0.33
        assert api.post(f"{BASE}/runs/{RUN}/finish", json=body).status_code == 409
        assert api.post(f"{BASE}/runs/run-nope-01/finish", json=body).status_code == 404
        bad = {"status": "running", "events_read": 0, "cards_posted": 0}
        assert api.post(f"{BASE}/runs/{RUN}/finish", json=bad).status_code == 422


class TestMonitors:
    PUT = {
        "monitor_id": "monitor_abc",
        "query": "Startups announcing a seed round",
        "processor": "base",
        "frequency": "1d",
        "status": "active",
        "charged_through": "2026-10-07T07:00:00Z",
    }

    def test_put_get_patch(self, api) -> None:
        resp = api.put(f"{BASE}/monitors/seed", json=self.PUT)
        assert resp.status_code == 200
        assert resp.json() == {
            "slot": "seed",
            "monitor_id": "monitor_abc",
            "query": "Startups announcing a seed round",
            "processor": "base",
            "frequency": "1d",
            "status": "active",
            "last_event_id": None,
            "charged_through": "2026-10-07T07:00:00Z",
        }
        resp = api.patch(f"{BASE}/monitors/seed", json={"last_event_id": "mevt_9"})
        assert resp.status_code == 200 and resp.json()["last_event_id"] == "mevt_9"
        resp = api.patch(
            f"{BASE}/monitors/seed",
            json={"charged_through": "2026-10-09T07:00:00Z", "status": "cancelled"},
        )
        assert resp.json()["status"] == "cancelled"
        assert resp.json()["charged_through"] == "2026-10-09T07:00:00Z"
        monitors = api.get(f"{BASE}/monitors").json()["monitors"]
        assert [m["slot"] for m in monitors] == ["seed"]
        # A run only gets ACTIVE monitors.
        assert _start(api)["monitors"] == []

    def test_bad_slot_and_body_422(self, api) -> None:
        assert api.put(f"{BASE}/monitors/bogus", json=self.PUT).status_code == 422
        for override in ({"processor": "core"}, {"frequency": "1h"},
                         {"charged_through": "2026-10-07T07:00:00"}, {"extra": 1}):
            assert api.put(f"{BASE}/monitors/seed", json={**self.PUT, **override}).status_code == 422
        api.put(f"{BASE}/monitors/seed", json=self.PUT)
        for body in ({}, {"last_event_id": None}, {"status": "paused"}, {"query": "x"}):
            assert api.patch(f"{BASE}/monitors/seed", json=body).status_code == 422, body

    def test_patch_missing_slot_404(self, api) -> None:
        assert api.patch(f"{BASE}/monitors/launch", json={"status": "cancelled"}).status_code == 404

    def test_monitor_id_reused_by_another_slot_409(self, api) -> None:
        api.put(f"{BASE}/monitors/seed", json=self.PUT)
        assert api.put(f"{BASE}/monitors/launch", json=self.PUT).status_code == 409


class TestCardsAndSeen:
    def test_post_card_201_then_dedupe_409(self, api, db_conn) -> None:
        _start(api)
        resp = _post_card(api)
        assert resp.status_code == 201
        assert set(resp.json()) == {"id", "tracked_company_id"}
        assert resp.json()["tracked_company_id"] is None
        dup = _post_card(api, make_payload(company="Raindrop Again"))
        assert dup.status_code == 409
        assert dup.json() == {"detail": "domain already posted"}
        with db_conn.cursor() as cur:
            cur.execute("SELECT cards_posted FROM launch_radar_runs")
            assert cur.fetchone()["cards_posted"] == 1
        db_conn.rollback()

    def test_post_card_tracked_company(self, api, db_conn) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        _start(api)
        assert _post_card(api).json()["tracked_company_id"] == "raindrop"

    def test_post_card_run_errors(self, api) -> None:
        assert _post_card(api, run_uuid="run-missing").status_code == 404
        _start(api)
        api.post(f"{BASE}/runs/{RUN}/finish", json={"status": "stopped", "events_read": 0, "cards_posted": 0})
        assert _post_card(api).status_code == 409

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p.update(domain="www.raindrop.ai"),  # not normalized
            lambda p: p.update(domain="Raindrop.ai"),  # not lower-case
            lambda p: p.update(surprise=True),  # extra key
            lambda p: p.pop("scores"),  # missing required key
            lambda p: p["scores"].update(talent=101),
            lambda p: p["ats"].update(provider="bamboohr"),
            lambda p: p.update(notable_facts=["x"] * 7),
            lambda p: p["leaders"][0].update(surprise=1),  # extra key, nested
            lambda p: p["event"].update(origin="rss"),  # not a known event origin
        ],
    )
    def test_post_card_invalid_payload_422(self, api, mutate) -> None:
        _start(api)
        payload = make_payload()
        mutate(payload)
        assert _post_card(api, payload).status_code == 422

    # Every URL field in the payload: (setter, nullable).
    URL_FIELDS = {
        "website": (lambda p, v: p.update(website=v), False),
        "careers_url": (lambda p, v: p.update(careers_url=v), True),
        "event.source_url": (lambda p, v: p["event"].update(source_url=v), True),
        "ats.board_url": (lambda p, v: p["ats"].update(board_url=v), True),
        "ats.checked_url": (lambda p, v: p["ats"].update(checked_url=v), True),
        "leaders.linkedin_url": (lambda p, v: p["leaders"][0].update(linkedin_url=v), True),
        "leaders.profile_url": (lambda p, v: p["leaders"][0].update(profile_url=v), True),
        "sources.url": (lambda p, v: p["sources"][0].update(url=v), False),
    }
    NOT_HTTP = [
        "javascript:alert(1)",
        "JavaScript:alert(document.cookie)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "ftp://example.com/x",
        "mailto:press@example.com",
        "//example.com/protocol-relative",
        "/relative/path",
        "example.com",
        "https://",
        "https:///no-host",
        " https://example.com",
        "https://exa mple.com",
        "https://example.com/" + "a" * 2000,
        "",
    ]

    @pytest.mark.parametrize("field", list(URL_FIELDS))
    @pytest.mark.parametrize("bad", NOT_HTTP)
    def test_post_card_non_http_url_is_422(self, api, db_conn, field: str, bad: str) -> None:
        _start(api)
        payload = make_payload()
        self.URL_FIELDS[field][0](payload, bad)
        resp = _post_card(api, payload)
        assert resp.status_code == 422, (field, bad)
        with db_conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM launch_radar_cards")
            assert cur.fetchone()["n"] == 0
        db_conn.rollback()

    @pytest.mark.parametrize("field", list(URL_FIELDS))
    def test_post_card_accepts_http_https_and_null_urls(self, api, db_conn, field: str) -> None:
        _start(api)
        set_url, nullable = self.URL_FIELDS[field]
        for i, good in enumerate(
            ["http://www.globenewswire.com/news/1", "HTTPS://Example.com/Path?q=1#x"]
            + ([None] if nullable else [])
        ):
            payload = make_payload(domain=f"ok{i}.ai")
            set_url(payload, good)
            assert _post_card(api, payload).status_code == 201, (field, good)

    @pytest.mark.parametrize("value", ["2026-09-17", "2026-09", None])
    def test_post_card_accepts_an_iso_day_month_or_no_announced_at(self, api, db_conn, value) -> None:
        _start(api)
        payload = make_payload()
        payload["event"]["announced_at"] = value
        assert _post_card(api, payload).status_code == 201

    @pytest.mark.parametrize(
        "value", ["September 17, 2026", "2026", "Q3 2026", "2026-9-17", "2026-09-17T00:00:00Z", "", "２０２６-09"]
    )
    def test_post_card_refuses_any_other_announced_at(self, api, db_conn, value) -> None:
        """The admin list sorts announced_at as text: only ISO day / month shapes sort as dates."""
        _start(api)
        payload = make_payload()
        payload["event"]["announced_at"] = value
        assert _post_card(api, payload).status_code == 422

    def test_post_card_accepts_the_backfill_origin(self, api, db_conn) -> None:
        """``radar.py backfill`` queues FindAll matches; their cards carry origin findall_backfill."""
        _start(api)
        payload = make_payload()
        payload["event"] = {**payload["event"], "origin": "findall_backfill", "announced_at": "2026-09-17",
                            "source_url": "https://techcrunch.com/2026/09/17/raindrop"}
        card_id = _post_card(api, payload).json()["id"]
        with db_conn.cursor() as cur:
            cur.execute("SELECT payload FROM launch_radar_cards WHERE id = %s", (card_id,))
            stored = cur.fetchone()["payload"]
        db_conn.rollback()
        assert stored["event"]["origin"] == "findall_backfill"
        assert stored["event"]["source_url"] == "https://techcrunch.com/2026/09/17/raindrop"

    def test_null_scores_stay_null(self, api, db_conn) -> None:
        """No people data / no funding data is stored as null, never 0."""
        _start(api)
        payload = make_payload()
        payload["scores"] = {"talent": None, "vc": None, "talent_reasons": [], "vc_reasons": []}
        payload["leaders"] = []
        payload["team_stats"] = None
        payload["event"] = None
        card_id = _post_card(api, payload).json()["id"]
        with db_conn.cursor() as cur:
            cur.execute("SELECT payload FROM launch_radar_cards WHERE id = %s", (card_id,))
            stored = cur.fetchone()["payload"]
        db_conn.rollback()
        assert stored["scores"]["talent"] is None and stored["scores"]["vc"] is None
        assert stored["team_stats"] is None and stored["event"] is None

    def test_seen(self, api, db_conn) -> None:
        _insert_company(db_conn, "raindrop-ai", "ashby", "raindrop", name="Raindrop AI")
        _start(api)
        card_id = _post_card(api, make_payload(domain="ghost.ai")).json()["id"]
        resp = api.get(
            f"{BASE}/seen",
            params=[("domain", "https://www.Ghost.ai/x"), ("domain", "fresh.io"),
                    ("name", "Raindrop AI"), ("name", "Unknown Co")],
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "domains": {"ghost.ai": {"card_id": card_id, "status": "new"}},
            "names": {"Raindrop AI": "raindrop-ai"},
        }
        assert api.get(f"{BASE}/seen").json() == {"domains": {}, "names": {}}

    def test_seen_reports_a_saved_card_so_the_loop_skips_it(self, api, db_conn) -> None:
        _start(api)
        card_id = _post_card(api, make_payload(domain="ghost.ai")).json()["id"]
        svc.set_status(db_conn, card_id, "saved", "admin@x.com")
        resp = api.get(f"{BASE}/seen", params=[("domain", "ghost.ai")])
        assert resp.status_code == 200
        assert resp.json()["domains"] == {"ghost.ai": {"card_id": card_id, "status": "saved"}}

    def test_seen_more_than_100_is_422(self, api) -> None:
        params = [("domain", f"d{i}.ai") for i in range(101)]
        assert api.get(f"{BASE}/seen", params=params).status_code == 422
        params = [("name", f"n{i}") for i in range(101)]
        assert api.get(f"{BASE}/seen", params=params).status_code == 422
        params = [("domain", f"d{i}.ai") for i in range(100)]
        assert api.get(f"{BASE}/seen", params=params).status_code == 200


class TestPrStep:
    def test_pr_candidates_and_set_pr(self, api, db_conn) -> None:
        _start(api)
        card_id = _post_card(api).json()["id"]
        _post_card(api, make_payload(domain="later.ai", pr_ready=False))
        cands = api.get(f"{BASE}/pr-candidates", params={"limit": 5}).json()["cards"]
        assert len(cands) == 1
        c = cands[0]
        assert {k: c[k] for k in ("id", "domain", "company", "ats_provider", "board_token", "job_count")} == {
            "id": card_id,
            "domain": "raindrop.ai",
            "company": "Raindrop AI",
            "ats_provider": "ashby",
            "board_token": "Raindrop",
            "job_count": 9,
        }
        resp = api.patch(f"{BASE}/cards/{card_id}/pr", json={"pr_url": PR_URL})
        assert resp.status_code == 200 and resp.json() == {"id": card_id, "pr_url": PR_URL}
        assert api.patch(f"{BASE}/cards/{card_id}/pr", json={"pr_url": PR_URL}).status_code == 409
        assert api.get(f"{BASE}/pr-candidates").json() == {"cards": []}

    def test_set_pr_errors(self, api, db_conn) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        _start(api)
        tracked = _post_card(api).json()["id"]
        assert api.patch(f"{BASE}/cards/{tracked}/pr", json={"pr_url": PR_URL}).status_code == 409
        assert api.patch(f"{BASE}/cards/999999/pr", json={"pr_url": PR_URL}).status_code == 404
        for url in (
            "https://github.com/someone-else/Job-Visualizer-Notifier/pull/1",
            "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1/files",
            "http://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1",
        ):
            assert api.patch(f"{BASE}/cards/{tracked}/pr", json={"pr_url": url}).status_code == 422
        # A deleted card is 404.
        other = _post_card(api, make_payload(domain="other.ai")).json()["id"]
        svc.set_status(db_conn, other, "archived", "x")
        svc.delete_card(db_conn, other, "x")
        assert api.patch(f"{BASE}/cards/{other}/pr", json={"pr_url": PR_URL}).status_code == 404

    def test_pr_candidates_offer_a_saved_card_first(self, api, db_conn) -> None:
        _start(api)
        newer = _post_card(api, make_payload(domain="newer.ai")).json()["id"]
        saved = _post_card(api, make_payload(domain="saved.ai")).json()["id"]
        archived = _post_card(api, make_payload(domain="archived.ai")).json()["id"]
        svc.set_status(db_conn, saved, "saved", "admin@x.com")
        svc.set_status(db_conn, archived, "archived", "admin@x.com")
        cands = api.get(f"{BASE}/pr-candidates", params={"limit": 5}).json()["cards"]
        assert [c["id"] for c in cands] == [saved, newer]
        assert api.get(f"{BASE}/pr-candidates").json()["cards"][0]["id"] == saved

    @pytest.mark.parametrize("limit", [0, 6])
    def test_pr_candidates_limit_bounds(self, api, limit) -> None:
        assert api.get(f"{BASE}/pr-candidates", params={"limit": limit}).status_code == 422


class TestRefreshRoutes:
    """``radar.py refresh``: GET /cards (the lookup) and PUT /cards/{id}/payload."""

    @staticmethod
    def _refreshed(domain: str = "raindrop.ai") -> dict[str, Any]:
        payload = make_payload(domain=domain, company="Raindrop Labs")
        payload["scores"] = {"talent": 61, "vc": 55, "talent_reasons": ["Sam Rivera: top school (Stanford)"],
                             "vc_reasons": ["CRV led (tier 2)"]}
        payload["issues"] = ["leaders from the brief (FindAll found none)"]
        return payload

    def _put(self, api: TestClient, card_id: int, payload: dict[str, Any]):
        return api.put(f"{BASE}/cards/{card_id}/payload", json={"payload": payload})

    @pytest.mark.parametrize("status", ["new", "saved", "archived"])
    def test_put_replaces_the_payload_and_keeps_status_and_posted_at(self, api, db_conn, status) -> None:
        _insert_company(db_conn, "raindrop", "ashby", "raindrop")
        _start(api)
        card_id = _post_card(api).json()["id"]
        with db_conn.cursor() as cur:  # a tracked card never gets a PR via the API; set one to see it kept
            cur.execute("UPDATE launch_radar_cards SET pr_url = %s WHERE id = %s", (PR_URL, card_id))
        db_conn.commit()
        if status != "new":
            svc.set_status(db_conn, card_id, status, "admin@x.com")
        before = _card(db_conn, card_id)

        resp = self._put(api, card_id, self._refreshed())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {k: body[k] for k in ("id", "domain", "status")} == {
            "id": card_id, "domain": "raindrop.ai", "status": status}
        after = _card(db_conn, card_id)
        assert after["payload"] == stored_payload(company="Raindrop Labs", scores=self._refreshed()["scores"],
                                                  issues=self._refreshed()["issues"])
        assert after["payload"]["scores"]["talent"] == 61
        assert after["status"] == status and after["posted_at"] == before["posted_at"]
        assert after["updated_at"] > before["updated_at"]
        assert after["company_name"] == "Raindrop Labs"
        for kept in ("tracked_company_id", "pr_url", "run_id", "archived_at", "updated_by", "domain"):
            assert after[kept] == before[kept], kept
        assert after["tracked_company_id"] == "raindrop" and after["pr_url"] == PR_URL

    def test_put_needs_no_running_run(self, api, db_conn) -> None:
        _start(api)
        card_id = _post_card(api).json()["id"]
        api.post(f"{BASE}/runs/{RUN}/finish", json={"status": "ok", "events_read": 0, "cards_posted": 1})
        assert self._put(api, card_id, self._refreshed()).status_code == 200

    def test_put_missing_or_deleted_card_is_404(self, api, db_conn) -> None:
        assert self._put(api, 999999, self._refreshed()).status_code == 404
        _start(api)
        card_id = _post_card(api).json()["id"]
        svc.set_status(db_conn, card_id, "archived", "x")
        svc.delete_card(db_conn, card_id, "x")
        resp = self._put(api, card_id, self._refreshed())
        assert resp.status_code == 404 and resp.json() == {"detail": "card not found"}
        row = _card(db_conn, card_id)
        assert row["status"] == "deleted" and row["payload"] is None  # the tombstone stays a tombstone

    def test_put_other_domain_is_422_and_changes_nothing(self, api, db_conn) -> None:
        _start(api)
        card_id = _post_card(api).json()["id"]
        before = _card(db_conn, card_id)
        resp = self._put(api, card_id, self._refreshed(domain="ghost.ai"))
        assert resp.status_code == 422
        assert "is not the card's domain" in resp.json()["detail"]
        assert _card(db_conn, card_id) == before

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p.update(surprise=True),
            lambda p: p.pop("scores"),
            lambda p: p["scores"].update(talent=101),
            lambda p: p["leaders"][0].update(source="brief"),  # leaders have no source field
            lambda p: p["leaders"][0].update(linkedin_url="javascript:alert(1)"),
            lambda p: p["sources"][0].update(url="data:text/html,<script>alert(1)</script>"),
            lambda p: p.update(website="ftp://raindrop.ai"),
            lambda p: p["event"].update(source_url="//news.example.com/x"),
        ],
    )
    def test_put_invalid_payload_is_422_and_changes_nothing(self, api, db_conn, mutate) -> None:
        _start(api)
        card_id = _post_card(api).json()["id"]
        before = _card(db_conn, card_id)
        payload = self._refreshed()
        mutate(payload)
        assert self._put(api, card_id, payload).status_code == 422
        assert _card(db_conn, card_id) == before

    def test_put_body_and_path_validation(self, api, db_conn) -> None:
        _start(api)
        card_id = _post_card(api).json()["id"]
        assert api.put(f"{BASE}/cards/0/payload", json={"payload": self._refreshed()}).status_code == 422
        assert api.put(f"{BASE}/cards/{card_id}/payload", json=self._refreshed()).status_code == 422  # unwrapped
        extra = {"payload": self._refreshed(), "run_uuid": RUN}
        assert api.put(f"{BASE}/cards/{card_id}/payload", json=extra).status_code == 422

    def test_get_cards_by_domain_and_missing_talent(self, api, db_conn) -> None:
        _start(api)
        scored = _post_card(api).json()["id"]
        blank = make_payload(domain="ghost.ai")
        blank["scores"] = {"talent": None, "vc": 40, "talent_reasons": [], "vc_reasons": ["x"]}
        blank["leaders"] = []
        unscored = _post_card(api, blank).json()["id"]
        gone_payload = make_payload(domain="gone.ai")
        gone_payload["scores"] = dict(blank["scores"])
        gone = _post_card(api, gone_payload).json()["id"]
        svc.set_status(db_conn, gone, "archived", "x")
        svc.delete_card(db_conn, gone, "x")
        svc.set_status(db_conn, unscored, "saved", "admin@x.com")

        by_domain = api.get(f"{BASE}/cards", params=[("domain", "https://www.Raindrop.ai/x"),
                                                     ("domain", "ghost.ai"), ("domain", "gone.ai")])
        assert by_domain.status_code == 200
        cards = by_domain.json()["cards"]
        assert [(c["id"], c["domain"], c["status"]) for c in cards] == [
            (scored, "raindrop.ai", "new"), (unscored, "ghost.ai", "saved")]
        assert cards[0]["payload"] == stored_payload()

        missing = api.get(f"{BASE}/cards", params={"missing_talent": "true"}).json()["cards"]
        assert [c["id"] for c in missing] == [unscored]  # the tombstone is never returned
        both = api.get(f"{BASE}/cards", params=[("domain", "raindrop.ai"), ("missing_talent", "true")])
        assert both.json() == {"cards": []}

    def test_get_cards_status_filter_and_keyset_paging(self, api, db_conn) -> None:
        _start(api)
        ids = []
        for i in range(5):
            payload = make_payload(domain=f"c{i}.ai")
            payload["scores"] = {"talent": None, "vc": None, "talent_reasons": [], "vc_reasons": []}
            ids.append(_post_card(api, payload).json()["id"])
        svc.set_status(db_conn, ids[1], "archived", "x")
        svc.set_status(db_conn, ids[3], "saved", "x")

        def get(*params: tuple[str, Any]) -> list[int]:
            resp = api.get(f"{BASE}/cards", params=[("missing_talent", "true"), *params])
            assert resp.status_code == 200, resp.text
            return [c["id"] for c in resp.json()["cards"]]

        assert get() == ids  # no status: every live one
        assert get(("status", "new"), ("status", "saved")) == [ids[0], ids[2], ids[3], ids[4]]
        assert get(("status", "archived")) == [ids[1]]
        assert get(("limit", 2)) == ids[:2]
        assert get(("limit", 2), ("after_id", ids[1])) == ids[2:4]
        assert get(("limit", 2), ("after_id", ids[3])) == ids[4:]
        assert get(("after_id", ids[4])) == []

    def test_get_cards_validation(self, api) -> None:
        assert api.get(f"{BASE}/cards").status_code == 422
        assert api.get(f"{BASE}/cards", params={"missing_talent": "false"}).status_code == 422
        many = [("domain", f"d{i}.ai") for i in range(101)]
        assert api.get(f"{BASE}/cards", params=many).status_code == 422
        for limit in (0, 501):
            resp = api.get(f"{BASE}/cards", params={"missing_talent": "true", "limit": limit})
            assert resp.status_code == 422
        assert api.get(f"{BASE}/cards", params={"missing_talent": "true", "limit": 500}).json() == {"cards": []}
        for bad in ({"status": "deleted"}, {"status": "starred"}, {"after_id": -1}):
            assert api.get(f"{BASE}/cards", params={"missing_talent": "true", **bad}).status_code == 422
