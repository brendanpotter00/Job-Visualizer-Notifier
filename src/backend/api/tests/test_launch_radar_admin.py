"""Admin Launch Radar routes (``/api/admin/launch-radar/*``), through the router.

Uses conftest's ``test_app`` (the real admin router, ``require_admin``
overridden to an admin by default). The auth tests pop the overrides so the
real ``get_current_user`` / ``require_admin`` chain runs.
"""

from __future__ import annotations

import json
import types
from typing import Annotated, Any, Union, get_args, get_origin

import pytest
from pydantic import AfterValidator, BaseModel, ValidationError

from api import models
from api.auth.dependencies import get_current_user, require_admin
from api.services import launch_radar as svc

from .conftest import _insert_admin, _insert_user, _make_user
from .test_launch_radar_service import (  # noqa: F401  (autouse isolation fixture)
    _launch_radar_isolation,
    make_payload,
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
            "counts": {"new": 0, "saved": 0, "archived": 0},
            "stats": {"lastRun": None, "spendUsd": 0.0, "capUsd": 5.0},
        }

    def test_card_shape_is_camel_case(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "raindrop.ai")
        svc.reserve_spend(db_conn, "run-0001", "findall.create", 0.46, "raindrop.ai", False)
        body = client.get(BASE, params={"status": "new"}).json()
        assert body["total"] == 1 and body["counts"] == {"new": 1, "saved": 0, "archived": 0}
        assert body["stats"]["spendUsd"] == 0.46
        assert body["stats"]["lastRun"]["status"] == "running"
        assert body["stats"]["lastRun"]["host"] == "test-host"
        assert set(body["stats"]["lastRun"]) == {"startedAt", "endedAt", "status", "host"}
        c = body["cards"][0]
        assert c["id"] == card and c["status"] == "new"
        assert c["trackedCompanyId"] is None and c["archivedAt"] is None
        assert "prUrl" not in c and "prReady" not in c  # the removed add-company PR step's fields
        assert c["domain"] == "raindrop.ai" and c["oneLiner"] == "Monitoring for AI agents"
        assert c["event"]["sourceUrl"] == "https://techcrunch.com/raindrop"
        assert c["scores"] == {  # a legacy card (scored before the blend): no parts, no basis
            "talent": 49,
            "vc": 55,
            "talentReasons": ["Sam Rivera: top employer (Apple)"],
            "vcReasons": ["CRV led (tier 2)"],
            "talentLeaders": None,
            "talentTeam": None,
            "talentBasis": None,
            "talentTeamReasons": [],
        }
        assert c["leaders"][0]["priorCompanies"] == ["Apple (Designer)"]
        assert c["leaders"][0]["yearsExperience"] == 8
        assert c["leadersDropped"] == 1
        # Schools and employers only: the team tally no longer counts prior exits.
        assert set(c["teamStats"]) == {
            "profilesFound", "teamSizeEstimate", "schools", "priorEmployers", "sampleNames",
        }
        assert c["funding"]["latestRound"]["leadInvestors"] == ["CRV"]
        assert c["ats"]["jobCount"] == 9
        assert c["parallelRunIds"]["findallId"] == "findall_1"
        assert c["timingsS"] == {"findall_s": 154.0}  # dict keys are data, not aliased
        assert c["costUsd"] == 0.3
        assert c["generatedAt"].startswith("2026-10-07T01:36:00")
        assert "postedAt" in c and "updatedBy" in c
        assert not any("_" in k for k in c if k != "timingsS")

    def test_a_stored_team_exit_count_is_never_sent(self, client, db_conn) -> None:
        """A card stored before the team tally dropped prior exits still lists, and its
        old ``ex_founders_with_exit`` stays out of the response (the page ignores it)."""
        start_test_run(db_conn)
        legacy = stored_payload()
        legacy["team_stats"]["ex_founders_with_exit"] = 2
        svc.insert_card(db_conn, "run-0001", legacy)
        (c,) = client.get(BASE, params={"status": "new"}).json()["cards"]
        assert "exFoundersWithExit" not in c["teamStats"]
        assert c["teamStats"]["priorEmployers"] == [{"name": "Amazon", "count": 2}]

    def test_a_stored_pr_flag_is_never_sent(self, client, db_conn) -> None:
        """A card stored while the add-company PR step existed still lists: its old
        ``pr_ready`` validates and stays out of the response, and so does a PR link
        left in the legacy ``pr_url`` column."""
        start_test_run(db_conn)
        legacy = stored_payload()
        legacy["pr_ready"] = True
        card = svc.insert_card(db_conn, "run-0001", legacy)["id"]
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE launch_radar_cards SET pr_url = %s WHERE id = %s",
                ("https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/333", card),
            )
        db_conn.commit()
        (c,) = client.get(BASE, params={"status": "new"}).json()["cards"]
        assert c["id"] == card and "prReady" not in c and "prUrl" not in c

    def test_blended_talent_is_camel_case(self, client, db_conn) -> None:
        start_test_run(db_conn)
        scores = {
            "talent": 72, "vc": 55, "talent_reasons": ["Sam Rivera: top employer (Apple)"],
            "vc_reasons": ["CRV led (tier 2)"], "talent_leaders": 37, "talent_team": 35,
            "talent_basis": "both", "talent_team_reasons": ["15 of the 19 schools listed across 33 profiles are top schools (+14)"],
        }
        svc.insert_card(db_conn, "run-0001", stored_payload(scores=scores))
        (c,) = client.get(BASE, params={"status": "new"}).json()["cards"]
        assert c["scores"] == {
            "talent": 72,
            "vc": 55,
            "talentReasons": ["Sam Rivera: top employer (Apple)"],
            "vcReasons": ["CRV led (tier 2)"],
            "talentLeaders": 37,
            "talentTeam": 35,
            "talentBasis": "both",
            "talentTeamReasons": ["15 of the 19 schools listed across 33 profiles are top schools (+14)"],
        }

    def test_ai_grade_is_camel_case(self, client, db_conn) -> None:
        start_test_run(db_conn)
        scores = {
            "talent": 66, "vc": 70, "talent_reasons": ["Karan Vaidya: top employer (Google)"],
            "vc_reasons": ["Lightspeed led (tier 1)"], "talent_leaders": 12, "talent_team": 22,
            "talent_basis": "both", "talent_team_reasons": ["7 of the 9 schools listed are top schools (+14)"],
            "talent_rules": 34,
            "talent_ai": {
                "score": 66, "parts": {"leaders": 26, "industry": 18, "team": 19, "track_record": 3},
                "confidence": "high", "industry": "AI agent integration infrastructure",
                "reasons": ["Team: Rubrik x3, Databricks x2"], "rubric_version": "v1",
                "graded_at": "2026-10-08T22:33:09Z",
            },
        }
        svc.insert_card(db_conn, "run-0001", stored_payload(scores=scores))
        (c,) = client.get(BASE, params={"status": "new"}).json()["cards"]
        assert c["scores"]["talent"] == 66 and c["scores"]["talentRules"] == 34
        assert c["scores"]["talentAi"] == {
            "score": 66,
            "parts": {"leaders": 26, "industry": 18, "team": 19, "trackRecord": 3},
            "confidence": "high",
            "industry": "AI agent integration infrastructure",
            "reasons": ["Team: Rubrik x3, Databricks x2"],
            "rubricVersion": "v1",
            "gradedAt": "2026-10-08T22:33:09Z",
        }

    def test_tabs_counts_order_and_paging(self, client, db_conn) -> None:
        a, b, c = _seed_cards(db_conn, "a.ai", "b.ai", "c.ai")
        svc.set_status(db_conn, a, "archived", "x")
        body = client.get(BASE, params={"status": "new"}).json()
        assert [x["id"] for x in body["cards"]] == [c, b]
        assert body["counts"] == {"new": 2, "saved": 0, "archived": 1}
        page2 = client.get(BASE, params={"status": "new", "limit": 1, "offset": 1}).json()
        assert [x["id"] for x in page2["cards"]] == [b] and page2["total"] == 2
        archived = client.get(BASE, params={"status": "archived"}).json()
        assert [x["id"] for x in archived["cards"]] == [a]
        assert archived["cards"][0]["archivedAt"] is not None

    def test_saved_tab(self, client, db_conn) -> None:
        a, b, c = _seed_cards(db_conn, "a.ai", "b.ai", "c.ai")
        svc.set_status(db_conn, a, "saved", "x")
        svc.set_status(db_conn, c, "saved", "x")
        body = client.get(BASE, params={"status": "saved"}).json()
        # The default sort (announced): equal dates, so newest posted first; only
        # the saved cards.
        assert [x["id"] for x in body["cards"]] == [c, a]
        assert all(x["status"] == "saved" for x in body["cards"])
        assert body["total"] == 2
        assert body["counts"] == {"new": 1, "saved": 2, "archived": 0}
        # The same counts ride on every tab's response.
        new = client.get(BASE, params={"status": "new"}).json()
        assert [x["id"] for x in new["cards"]] == [b]
        assert new["counts"] == body["counts"]
        page2 = client.get(BASE, params={"status": "saved", "limit": 1, "offset": 1}).json()
        assert [x["id"] for x in page2["cards"]] == [a] and page2["total"] == 2

    @pytest.mark.parametrize(
        "params",
        [{}, {"status": "deleted"}, {"status": "bogus"}, {"status": "new", "limit": 101},
         {"status": "new", "limit": 0}, {"status": "new", "offset": -1},
         {"status": "new", "sort": "bogus"}, {"status": "new", "sort": "TALENT"},
         {"status": "new", "sort": ""}, {"status": "new", "sort": "posted_at DESC"},
         {"status": "new", "sort": "talent; DROP TABLE launch_radar_cards"}],
    )
    def test_bad_query_is_422(self, client, params) -> None:
        assert client.get(BASE, params=params).status_code == 422

    def test_sort_param_orders_the_page(self, client, db_conn) -> None:
        start_test_run(db_conn)

        def card(domain: str, talent: int | None, vc: int | None, announced: str) -> int:
            base = stored_payload(domain=domain)
            payload = {
                **base,
                "event": {**base["event"], "announced_at": announced},
                "scores": {**base["scores"], "talent": talent, "vc": vc},
            }
            return svc.insert_card(db_conn, "run-0001", payload)["id"]

        a = card("a.ai", 90, 10, "2026-09-01")
        b = card("b.ai", None, 80, "2026-09-30")
        c = card("c.ai", 40, None, "2026-09-15")

        def order(**params: str) -> list[int]:
            resp = client.get(BASE, params={"status": "new", **params})
            assert resp.status_code == 200, resp.text
            return [x["id"] for x in resp.json()["cards"]]

        assert order() == [b, c, a]  # default: newest announcement first
        assert order(sort="announced") == [b, c, a]
        assert order(sort="talent") == [a, c, b]  # unscored last
        assert order(sort="vc") == [b, a, c]
        assert order(sort="added") == [c, b, a]  # newest posted first
        page = client.get(BASE, params={"status": "new", "sort": "talent", "limit": 1, "offset": 1})
        assert [x["id"] for x in page.json()["cards"]] == [c] and page.json()["total"] == 3

    def test_deleted_cards_never_reach_the_client(self, client, db_conn) -> None:
        a, b = _seed_cards(db_conn, "a.ai", "b.ai")
        svc.set_status(db_conn, a, "archived", "x")
        svc.delete_card(db_conn, a, "x")
        for status in ("new", "saved", "archived"):
            body = client.get(BASE, params={"status": status}).json()
            assert a not in [x["id"] for x in body["cards"]]
            assert body["counts"] == {"new": 1, "saved": 0, "archived": 0}


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


def _store_raw_payload(db_conn: Any, card_id: int, payload: dict[str, Any]) -> None:
    """Write a payload straight to the row, past the input model (an old or hand-edited row)."""
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE launch_radar_cards SET payload = %s::jsonb WHERE id = %s",
            (json.dumps(payload), card_id),
        )
    db_conn.commit()


def _payload_with_bad_stored_values(domain: str) -> dict[str, Any]:
    p = make_payload(domain=domain)
    p["website"] = "javascript:alert(1)"
    p["careers_url"] = "data:text/html,x"
    p["event"] = {**p["event"], "source_url": "ftp://example.com/x", "announced_at": "September 17, 2026"}
    p["ats"] = {**p["ats"], "board_url": "//jobs.example.com", "checked_url": "https://ok.example.com/api"}
    p["leaders"] = [{**p["leaders"][0], "linkedin_url": "linkedin.com/in/x", "profile_url": "https://ok.example.com/p"}]
    p["sources"] = [
        {"url": "javascript:void(0)", "title": "bad", "field": None},
        {"url": "https://techcrunch.com/raindrop", "title": "good", "field": None},
    ]
    return p


class TestOutputTolerance:
    """A stored value that fails the INPUT rules is nulled on the way out, never a
    reason to drop the card from the list or to 500 a PATCH that already committed."""

    def test_list_keeps_the_card_and_nulls_the_bad_values(self, client, db_conn, caplog) -> None:
        (card,) = _seed_cards(db_conn, "raindrop.ai")
        _store_raw_payload(db_conn, card, _payload_with_bad_stored_values("raindrop.ai"))
        resp = client.get(BASE, params={"status": "new"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1 and [c["id"] for c in body["cards"]] == [card]
        c = body["cards"][0]
        assert c["website"] == "https://raindrop.ai"  # the contract's own default, never null
        assert c["careersUrl"] is None
        assert c["event"]["sourceUrl"] is None and c["event"]["announcedAt"] is None
        assert c["event"]["headline"] == "Raindrop raises $35M Series A"  # the rest is kept
        assert c["ats"]["boardUrl"] is None and c["ats"]["checkedUrl"] == "https://ok.example.com/api"
        assert c["leaders"][0]["linkedinUrl"] is None
        assert c["leaders"][0]["profileUrl"] == "https://ok.example.com/p"
        assert [s["title"] for s in c["sources"]] == ["good"]
        assert f"launch radar card {card}" in caplog.text and "event.announced_at" in caplog.text
        # The stored row is untouched: only the response is cleaned.
        assert _db_card(db_conn, card)["payload"]["website"] == "javascript:alert(1)"

    def test_patch_on_such_a_card_returns_it(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "raindrop.ai")
        _store_raw_payload(db_conn, card, _payload_with_bad_stored_values("raindrop.ai"))
        resp = client.patch(f"{BASE}/{card}", json={"status": "saved", "from": "new"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "saved" and resp.json()["careersUrl"] is None

    def test_input_models_still_refuse_the_same_values(self) -> None:
        bad = _payload_with_bad_stored_values("raindrop.ai")
        with pytest.raises(ValidationError) as exc:
            models.LaunchRadarPayload.model_validate(bad)
        failed = {".".join(str(p) for p in e["loc"]) for e in exc.value.errors()}
        assert {"website", "careers_url", "event.source_url", "event.announced_at", "ats.board_url",
                "leaders.0.linkedin_url", "sources.0.url"} <= failed

    def test_every_url_field_is_tolerated_on_output(self) -> None:
        """Walk the payload models for every field carrying the URL rule: each one
        must be in LAUNCH_RADAR_URL_PATHS, which ``tolerate_stored_payload`` handles.
        A URL field added without it would fail the card on output again."""
        found: set[str] = set()

        def is_url_rule(meta: object) -> bool:
            return isinstance(meta, AfterValidator) and meta.func is models._launch_radar_http_url

        def walk(tp: Any, path: str) -> None:
            origin = get_origin(tp)
            if origin is Annotated:
                base, *meta = get_args(tp)
                if any(is_url_rule(m) for m in meta):
                    found.add(path)
                else:
                    walk(base, path)
            elif origin in (Union, types.UnionType):
                for arg in get_args(tp):
                    walk(arg, path)
            elif origin is list:
                walk(get_args(tp)[0], f"{path}[]")
            elif isinstance(tp, type) and issubclass(tp, BaseModel):
                for name, field in tp.model_fields.items():
                    sub = f"{path}.{name}" if path else name
                    if any(is_url_rule(m) for m in field.metadata):
                        found.add(sub)
                    else:
                        walk(field.annotation, sub)

        walk(models.LaunchRadarPayload, "")
        assert found == models.LAUNCH_RADAR_URL_PATHS


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

    def test_save_then_unsave(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        resp = client.patch(f"{BASE}/{card}", json={"status": "saved"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved" and resp.json()["archivedAt"] is None
        assert resp.json()["updatedBy"] == "test@example.com"
        assert resp.json()["domain"] == "a.ai"  # the full card comes back
        resp = client.patch(f"{BASE}/{card}", json={"status": "new"})
        assert resp.status_code == 200 and resp.json()["status"] == "new"

    def test_archive_a_saved_card_and_restore_it_to_new(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        client.patch(f"{BASE}/{card}", json={"status": "saved"})
        resp = client.patch(f"{BASE}/{card}", json={"status": "archived"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived" and resp.json()["archivedAt"]
        resp = client.patch(f"{BASE}/{card}", json={"status": "new"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "new" and resp.json()["archivedAt"] is None

    # Every allowed move, from each live status (CONTRACT §1.5 lifecycle).
    @pytest.mark.parametrize(
        ("setup", "target"),
        [
            ((), "saved"),  # Save
            ((), "archived"),  # Archive
            (("saved",), "new"),  # Unsave
            (("saved",), "archived"),  # Archive a saved card
            (("archived",), "new"),  # Restore
        ],
    )
    def test_allowed_transitions_are_200(self, client, db_conn, setup, target) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        for step in setup:
            svc.set_status(db_conn, card, step, "x")
        resp = client.patch(f"{BASE}/{card}", json={"status": target})
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == target
        assert _db_card(db_conn, card)["status"] == target

    # Every refused move: the same state, and archived -> saved.
    @pytest.mark.parametrize(
        ("setup", "target", "detail"),
        [
            ((), "new", "card is already new"),
            (("saved",), "saved", "card is already saved"),
            (("archived",), "archived", "card is already archived"),
            (("archived",), "saved", "card is archived; only a new card can move to saved"),
        ],
    )
    def test_refused_transitions_are_409(self, client, db_conn, setup, target, detail) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        for step in setup:
            svc.set_status(db_conn, card, step, "x")
        before = _db_card(db_conn, card)
        resp = client.patch(f"{BASE}/{card}", json={"status": target})
        assert resp.status_code == 409
        assert resp.json() == {"detail": detail}
        after = _db_card(db_conn, card)
        assert after["status"] == before["status"] and after["updated_at"] == before["updated_at"]

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
        for status in ("new", "saved", "archived"):
            assert client.patch(f"{BASE}/{card}", json={"status": status}).status_code == 404
        assert client.patch(f"{BASE}/999999", json={"status": "saved"}).status_code == 404

    # The page sends ``from`` on every action: the card's tab when it was clicked.
    @pytest.mark.parametrize(
        ("setup", "body"),
        [
            ((), {"status": "saved", "from": "new"}),  # Save
            (("saved",), {"status": "new", "from": "saved"}),  # Unsave
            ((), {"status": "archived", "from": "new"}),  # Archive from New
            (("saved",), {"status": "archived", "from": "saved"}),  # Archive from Saved
            (("archived",), {"status": "new", "from": "archived"}),  # Restore
        ],
    )
    def test_every_action_with_its_from_is_200(self, client, db_conn, setup, body) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        for step in setup:
            svc.set_status(db_conn, card, step, "x")
        resp = client.patch(f"{BASE}/{card}", json=body)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == body["status"]

    def test_a_stale_unsave_does_not_restore_an_archived_card(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        client.patch(f"{BASE}/{card}", json={"status": "saved", "from": "new"})
        client.patch(f"{BASE}/{card}", json={"status": "archived", "from": "saved"})  # another tab
        resp = client.patch(f"{BASE}/{card}", json={"status": "new", "from": "saved"})  # the stale Unsave
        assert resp.status_code == 409
        assert resp.json() == {"detail": "card is archived, not saved; reload and try again"}
        assert _db_card(db_conn, card)["status"] == "archived"
        # Without ``from`` (an older client) the same request still restores, as before.
        assert client.patch(f"{BASE}/{card}", json={"status": "new"}).json()["status"] == "new"

    @pytest.mark.parametrize(
        "body",
        [
            {"status": "deleted"},
            {"status": "archived", "extra": 1},
            {},
            {"status": "archived", "from": "deleted"},
            {"status": "archived", "from": "starred"},
            {"from": "new"},
        ],
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

    def test_delete_saved_card_is_409(self, client, db_conn) -> None:
        (card,) = _seed_cards(db_conn, "a.ai")
        client.patch(f"{BASE}/{card}", json={"status": "saved"})
        resp = client.delete(f"{BASE}/{card}")
        assert resp.status_code == 409
        assert resp.json() == {"detail": "card is saved; archive it before deleting it permanently"}
        assert _db_card(db_conn, card)["status"] == "saved"

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
