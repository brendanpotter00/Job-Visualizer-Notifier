"""Admin Launch Radar routes (``/api/admin/launch-radar/*``), through the router.

Uses conftest's ``test_app`` (the real admin router, ``require_admin``
overridden to an admin by default). The auth tests pop the overrides so the
real ``get_current_user`` / ``require_admin`` chain runs.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.auth.dependencies import get_current_user, require_admin
from api.services import launch_radar as svc

from .conftest import _insert_admin, _insert_user, _make_user
from .test_launch_radar_service import (  # noqa: F401  (autouse isolation fixture)
    _launch_radar_isolation,
    start_test_run,
    stored_payload,
)

BASE = "/api/admin/launch-radar/cards"


def _seed_cards(db_conn: Any, *domains: str) -> list[int]:
    start_test_run(db_conn)
    return [svc.insert_card(db_conn, "run-0001", stored_payload(domain=d))["id"] for d in domains]


def _db_card(db_conn: Any, card_id: int) -> dict[str, Any]:
    with db_conn.cursor() as cur:
        cur.execute("SELECT * FROM launch_radar_cards WHERE id = %s", (card_id,))
        row = cur.fetchone()
    db_conn.rollback()
    return dict(row)


class TestList:
    def test_empty(self, client) -> None:
        resp = client.get(BASE, params={"status": "new"})
        assert resp.status_code == 200
        assert resp.json() == {
            "cards": [],
            "total": 0,
            "counts": {"new": 0, "archived": 0},
            "stats": {"lastRun": None, "spendUsd": 0.0, "capUsd": 5.0},
        }

    def test_card_shape_is_camel_case(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "raindrop.ai")
        svc.reserve_spend(db_conn, "run-0001", "findall.create", 0.46, "raindrop.ai", False)
        body = client.get(BASE, params={"status": "new"}).json()
        assert body["total"] == 1 and body["counts"] == {"new": 1, "archived": 0}
        assert body["stats"]["spendUsd"] == 0.46
        assert body["stats"]["lastRun"]["status"] == "running"
        assert body["stats"]["lastRun"]["host"] == "test-host"
        assert set(body["stats"]["lastRun"]) == {"startedAt", "endedAt", "status", "host"}
        c = body["cards"][0]
        assert c["id"] == card and c["status"] == "new"
        assert c["trackedCompanyId"] is None and c["prUrl"] is None and c["archivedAt"] is None
        assert c["domain"] == "raindrop.ai" and c["oneLiner"] == "Monitoring for AI agents"
        assert c["event"]["sourceUrl"] == "https://techcrunch.com/raindrop"
        assert c["scores"] == {
            "talent": 49,
            "vc": 55,
            "talentReasons": ["Sam Rivera: top employer (Apple)"],
            "vcReasons": ["CRV led (tier 2)"],
        }
        assert c["leaders"][0]["priorCompanies"] == ["Apple (Designer)"]
        assert c["leaders"][0]["yearsExperience"] == 8
        assert c["leadersDropped"] == 1
        assert c["teamStats"]["exFoundersWithExit"] == 0
        assert c["funding"]["latestRound"]["leadInvestors"] == ["CRV"]
        assert c["ats"]["jobCount"] == 9 and c["prReady"] is True
        assert c["parallelRunIds"]["findallId"] == "findall_1"
        assert c["timingsS"] == {"findall_s": 154.0}  # dict keys are data, not aliased
        assert c["costUsd"] == 0.3
        assert c["generatedAt"].startswith("2026-10-07T01:36:00")
        assert "postedAt" in c and "updatedBy" in c
        assert not any("_" in k for k in c if k != "timingsS")

    def test_tabs_counts_order_and_paging(self, client, db_conn) -> None:
        a, b, c = _seed_cards(db_conn, "a.ai", "b.ai", "c.ai")
        svc.set_status(db_conn, a, "archived", "x")
        body = client.get(BASE, params={"status": "new"}).json()
        assert [x["id"] for x in body["cards"]] == [c, b]
        assert body["counts"] == {"new": 2, "archived": 1}
        page2 = client.get(BASE, params={"status": "new", "limit": 1, "offset": 1}).json()
        assert [x["id"] for x in page2["cards"]] == [b] and page2["total"] == 2
        archived = client.get(BASE, params={"status": "archived"}).json()
        assert [x["id"] for x in archived["cards"]] == [a]
        assert archived["cards"][0]["archivedAt"] is not None

    @pytest.mark.parametrize(
        "params",
        [{}, {"status": "deleted"}, {"status": "bogus"}, {"status": "new", "limit": 101},
         {"status": "new", "limit": 0}, {"status": "new", "offset": -1}],
    )
    def test_bad_query_is_422(self, client, params) -> None:
        assert client.get(BASE, params=params).status_code == 422

    def test_deleted_cards_never_reach_the_client(self, client, db_conn) -> None:
        a, b = _seed_cards(db_conn, "a.ai", "b.ai")
        svc.set_status(db_conn, a, "archived", "x")
        svc.delete_card(db_conn, a, "x")
        for status in ("new", "archived"):
            body = client.get(BASE, params={"status": status}).json()
            assert a not in [x["id"] for x in body["cards"]]
            assert body["counts"] == {"new": 1, "archived": 0}


    def test_one_unreadable_payload_does_not_blank_the_list(self, client, db_conn) -> None:
        good, bad = _seed_cards(db_conn, "raindrop.ai", "ghost.ai")
        with db_conn.cursor() as cur:  # an older shape: a field the strict model no longer accepts
            cur.execute(
                "UPDATE launch_radar_cards SET payload = payload || '{\"legacy_field\": 1}'::jsonb "
                "WHERE id = %s",
                (bad,),
            )
        db_conn.commit()
        resp = client.get(BASE, params={"status": "new"})
        assert resp.status_code == 200
        assert [c["id"] for c in resp.json()["cards"]] == [good]


class TestPatch:
    def test_archive_then_restore(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        resp = client.patch(f"{BASE}/{card}", json={"status": "archived"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived" and resp.json()["archivedAt"]
        assert resp.json()["updatedBy"] == "test@example.com"
        resp = client.patch(f"{BASE}/{card}", json={"status": "new"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "new" and resp.json()["archivedAt"] is None

    def test_same_state_is_409(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        assert client.patch(f"{BASE}/{card}", json={"status": "new"}).status_code == 409
        client.patch(f"{BASE}/{card}", json={"status": "archived"})
        assert client.patch(f"{BASE}/{card}", json={"status": "archived"}).status_code == 409

    def test_missing_or_deleted_is_404(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        assert client.patch(f"{BASE}/999999", json={"status": "archived"}).status_code == 404
        svc.set_status(db_conn, card, "archived", "x")
        svc.delete_card(db_conn, card, "x")
        assert client.patch(f"{BASE}/{card}", json={"status": "new"}).status_code == 404

    @pytest.mark.parametrize(
        "body", [{"status": "deleted"}, {"status": "archived", "extra": 1}, {}]
    )
    def test_bad_body_is_422(self, client, db_conn, body) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        assert client.patch(f"{BASE}/{card}", json=body).status_code == 422

    def test_card_id_must_be_positive(self, client) -> None:
        assert client.patch(f"{BASE}/0", json={"status": "archived"}).status_code == 422


class TestDelete:
    def test_delete_archived_tombstones(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        client.patch(f"{BASE}/{card}", json={"status": "archived"})
        resp = client.delete(f"{BASE}/{card}")
        assert resp.status_code == 204 and resp.content == b""
        row = _db_card(db_conn, card)
        assert row["status"] == "deleted" and row["payload"] is None
        assert row["domain"] == "a.ai" and row["updated_by"] == "test@example.com"
        # Already deleted -> 404.
        assert client.delete(f"{BASE}/{card}").status_code == 404

    def test_delete_new_card_is_409(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        assert client.delete(f"{BASE}/{card}").status_code == 409
        assert _db_card(db_conn, card)["status"] == "new"

    def test_delete_missing_is_404(self, client) -> None:
        assert client.delete(f"{BASE}/999999").status_code == 404


class TestAuth:
    """Every Launch Radar admin route sits behind require_admin."""

    ROUTES = (
        ("get", BASE + "?status=new", None),
        ("patch", BASE + "/1", {"status": "archived"}),
        ("delete", BASE + "/1", None),
    )

    def test_without_credentials_401(self, client, test_app) -> None:
        saved_admin = test_app.dependency_overrides.pop(require_admin, None)
        saved_current = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            for method, url, body in self.ROUTES:
                kwargs = {"json": body} if body is not None else {}
                resp = getattr(client, method)(url, **kwargs)
                assert resp.status_code == 401, (method, url)
        finally:
            test_app.dependency_overrides[get_current_user] = saved_current
            test_app.dependency_overrides[require_admin] = saved_admin

    def test_signed_in_non_admin_403(self, client, test_app, db_conn) -> None:
        _insert_user(db_conn, _make_user({"email": "test@example.com"}))
        saved_admin = test_app.dependency_overrides.pop(require_admin, None)
        try:
            for method, url, body in self.ROUTES:
                kwargs = {"json": body} if body is not None else {}
                resp = getattr(client, method)(url, **kwargs)
                assert resp.status_code == 403, (method, url)
        finally:
            test_app.dependency_overrides[require_admin] = saved_admin

    def test_real_admin_grant_200(self, client, test_app, db_conn) -> None:
        user = _make_user({"email": "test@example.com"})
        _insert_user(db_conn, user)
        _insert_admin(db_conn, user["id"])
        saved_admin = test_app.dependency_overrides.pop(require_admin, None)
        try:
            assert client.get(BASE, params={"status": "new"}).status_code == 200
        finally:
            test_app.dependency_overrides[require_admin] = saved_admin
