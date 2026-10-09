"""Backend client: auth header, 402 -> BudgetExceeded, 409 -> DomainSeen, retry rules."""

import json

import httpx
import pytest
from launch_radar.backend_client import (
    BackendClient,
    BackendError,
    BudgetExceeded,
    DomainSeen,
    PrRequestNotFound,
)
from tests.unit.launch_radar_fakes import FakeBackend


def _client(fb: FakeBackend, key: str | None = "k-123") -> BackendClient:
    return BackendClient("http://backend.test", key, transport=fb.transport())


def test_sends_internal_key_only_when_set():
    fb = FakeBackend()
    _client(fb).list_monitors()
    assert fb.requests[-1].headers["X-Internal-Key"] == "k-123"
    _client(fb, None).list_monitors()
    assert "X-Internal-Key" not in fb.requests[-1].headers


def test_reserve_refused_on_run_budget_and_cap():
    fb = FakeBackend(cap=0.2)
    c = _client(fb)
    c.start_run("run-aaaaaaaa", "h", 0.15)
    assert c.reserve("run-aaaaaaaa", "findall.create", 0.1)["over_cap"] is False
    with pytest.raises(BudgetExceeded) as e:
        c.reserve("run-aaaaaaaa", "task_run.create(brief)", 0.1)
    assert e.value.reason == "run_budget" and e.value.run_spend == 0.1
    c.start_run("run-bbbbbbbb", "h", 1.0)
    with pytest.raises(BudgetExceeded) as e2:
        c.reserve("run-bbbbbbbb", "task_run.create(pro)", 0.11)
    assert e2.value.reason == "cap" and e2.value.cap == 0.2
    # the refused reservations were not recorded
    assert [s["step"] for s in fb.spend] == ["findall.create"]


def test_accrued_reservation_always_recorded_and_flags_over_cap():
    fb = FakeBackend(cap=0.05)
    c = _client(fb)
    c.start_run("run-cccccccc", "h", 0.1)
    r = c.reserve("run-cccccccc", "monitor.accrued", 0.09, accrued=True)
    assert r["over_cap"] is True
    assert fb.total() == 0.09


def test_post_card_409_duplicate_is_domain_seen():
    fb = FakeBackend()
    c = _client(fb)
    c.start_run("run-dddddddd", "h", 1.0)
    payload = {"domain": "raindrop.ai", "ats": {"provider": "none", "board_token": None}, "company": "R"}
    assert c.post_card("run-dddddddd", payload)["id"] == 1
    with pytest.raises(DomainSeen):
        c.post_card("run-dddddddd", payload)


def test_post_card_other_409_is_an_error():
    fb = FakeBackend()
    c = _client(fb)
    c.start_run("run-eeeeeeee", "h", 1.0)
    c.finish_run("run-eeeeeeee", "ok", 0, 0, None)
    with pytest.raises(BackendError) as e:
        c.post_card("run-eeeeeeee", {"domain": "x.ai", "ats": {"provider": "none"}})
    assert e.value.status == 409 and e.value.detail == "run not running"


def test_get_is_retried_on_connection_error_but_post_is_not():
    calls = {"GET": 0, "POST": 0}

    def handler(request):
        calls[request.method] += 1
        if calls[request.method] < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"monitors": []})

    c = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(handler))
    assert c.list_monitors() == []
    assert calls["GET"] == 3
    with pytest.raises(httpx.ConnectError):
        c.reserve("run-ffffffff", "s", 0.01)
    assert calls["POST"] == 1


def test_seen_chunks_at_100_and_merges():
    fb = FakeBackend()
    fb.cards["d150.ai"] = {"id": 9, "status": "archived"}
    fb.tracked_names["acme"] = "acme"
    c = _client(fb)
    doms = [f"d{i}.ai" for i in range(160)]
    out = c.seen(doms, ["Acme", "Other"])
    assert out == {"domains": {"d150.ai": {"card_id": 9, "status": "archived"}}, "names": {"Acme": "acme"}}
    seen_reqs = [r for r in fb.requests if r.url.path.endswith("/seen")]
    assert len(seen_reqs) == 2
    assert c.seen([], []) == {"domains": {}, "names": {}}


def test_errors_never_include_the_key():
    def handler(request):
        return httpx.Response(500, json={"detail": "internal error"})

    c = BackendClient("http://backend.test", "super-secret-key", transport=httpx.MockTransport(handler))
    with pytest.raises(BackendError) as e:
        c.list_monitors()
    assert "super-secret-key" not in str(e.value)
    assert str(e.value) == "GET /monitors -> 500: internal error"


def test_finish_run_clips_notes():
    fb = FakeBackend()
    c = _client(fb)
    c.start_run("run-gggggggg", "h", 1.0)
    c.finish_run("run-gggggggg", "ok", 3, 1, "x" * 900)
    body = json.loads(fb.requests[-1].content)
    assert len(body["notes"]) == 500 and body["events_read"] == 3


def test_cards_pages_by_id_until_a_short_page_and_passes_statuses(monkeypatch):
    from launch_radar import backend_client

    monkeypatch.setattr(backend_client, "CARDS_LIMIT", 2)
    fb = FakeBackend()
    for i, (dom, status) in enumerate((("a.ai", "new"), ("b.ai", "archived"), ("c.ai", "saved"),
                                       ("d.ai", "new"), ("e.ai", "new")), start=1):
        fb.cards[dom] = {"id": i, "status": status, "payload": {"scores": {"talent": None}},
                         "tracked_company_id": None}
    c = _client(fb)
    got = c.cards(missing_talent=True, statuses=("new", "saved"))
    assert [card["domain"] for card in got] == ["a.ai", "c.ai", "d.ai", "e.ai"]
    assert [(q["after_id"], q["statuses"]) for q in fb.card_queries] == [
        (0, {"new", "saved"}), (3, {"new", "saved"}), (5, {"new", "saved"})]
    fb.card_queries.clear()
    assert [card["domain"] for card in c.cards(missing_talent=True)] == ["a.ai", "b.ai", "c.ai", "d.ai", "e.ai"]
    assert fb.card_queries[0]["statuses"] == {"new", "saved", "archived"}  # no status param: every live one


def test_cards_all_sends_the_explicit_opt_in_and_pages(monkeypatch):
    from launch_radar import backend_client

    monkeypatch.setattr(backend_client, "CARDS_LIMIT", 2)
    fb = FakeBackend()
    for i, dom in enumerate(("a.ai", "b.ai", "c.ai"), start=1):
        fb.cards[dom] = {"id": i, "status": "archived" if i == 2 else "new", "payload": {"scores": {"talent": 4}},
                         "tracked_company_id": None}
    c = _client(fb)
    assert [card["domain"] for card in c.cards(all_cards=True)] == ["a.ai", "b.ai", "c.ai"]
    params = [r.url.params for r in fb.requests]
    assert all(p.get("all") == "true" and "missing_talent" not in p and "domain" not in p for p in params)
    assert [q["after_id"] for q in fb.card_queries] == [0, 2]
    for bad in ({"all_cards": True, "domains": ["a.ai"]}, {"all_cards": True, "missing_talent": True}, {}):
        with pytest.raises(ValueError):
            c.cards(**bad)


def test_missing_talent_means_the_leaders_part_is_null():
    fb = FakeBackend()
    rows = {
        "legacy-null.ai": {"talent": None},  # legacy card, no leader data: selected
        "legacy-scored.ai": {"talent": 30},
        "team-only.ai": {"talent": 12, "talent_leaders": None, "talent_team": 6, "talent_basis": "team"},  # selected
        "both.ai": {"talent": 18, "talent_leaders": 12, "talent_team": 6, "talent_basis": "both"},
    }
    for i, (dom, scores) in enumerate(rows.items(), start=1):
        fb.cards[dom] = {"id": i, "status": "new", "payload": {"scores": scores}, "tracked_company_id": None}
    assert [card["domain"] for card in _client(fb).cards(missing_talent=True)] == ["legacy-null.ai", "team-only.ai"]


# ---- add-company PR requests (saved-pr/PLAN.md §3.3) ---------------------------------------------
PR_URL = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/9"


def test_pr_next_claims_then_204_is_none():
    fb = FakeBackend()
    cid = fb.add_card("acme.ai", company="Acme")
    fb.add_pr_request(cid)
    c = _client(fb)
    claim = c.pr_next()
    assert claim["card_id"] == cid and claim["company"] == "Acme" and claim["attempts"] == 1
    assert claim["latest_round"] == {"round": "Seed", "amount_usd": "$4M", "announced_at": "2026-09-01"}
    req = fb.requests[-1]
    assert (req.method, req.url.path, json.loads(req.content)) == (
        "POST", "/api/internal/launch-radar/pr-requests/next", {})
    assert req.headers["X-Internal-Key"] == "k-123"
    assert c.pr_next() is None


def test_pr_next_is_never_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    c = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ConnectError):
        c.pr_next()
    assert len(calls) == 1


def test_pr_next_error_status_raises():
    c = BackendClient("http://backend.test", "k",
                      transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"detail": "x"})))
    with pytest.raises(BackendError) as e:
        c.pr_next()
    assert e.value.status == 500 and e.value.path == "/pr-requests/next"


def test_pr_get_and_404():
    fb = FakeBackend()
    cid = fb.add_card("acme.ai", status="new")
    fb.add_pr_request(cid, "in_progress")
    c = _client(fb)
    row = c.pr_get(cid)
    assert row["status"] == "in_progress" and row["card_status"] == "new"
    with pytest.raises(PrRequestNotFound):
        c.pr_get(cid + 50)


def test_pr_get_is_retried_on_connection_error():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"card_id": 1, "status": "in_progress", "card_status": "saved"})

    c = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(handler))
    assert c.pr_get(1)["card_status"] == "saved" and len(calls) == 3


def test_pr_result_body_and_errors():
    fb = FakeBackend()
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "in_progress", attempts=1)
    c = _client(fb)
    row = c.pr_result(cid, "open", pr_url=PR_URL)
    assert row["status"] == "open" and row["pr_number"] == 9
    assert json.loads(fb.requests[-1].content) == {"outcome": "open", "pr_url": PR_URL, "reason": None}
    assert c.pr_result(cid, "open", pr_url=PR_URL)["status"] == "open"  # identical repeat: no-op
    with pytest.raises(BackendError) as e:
        c.pr_result(cid, "failed", reason="gh_error")
    assert e.value.status == 409
    with pytest.raises(PrRequestNotFound):
        c.pr_result(999, "failed", reason="gh_error")


def test_pr_result_is_never_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    c = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ConnectError):
        c.pr_result(1, "failed", reason="other")
    with pytest.raises(httpx.ConnectError):
        c.pr_requeue(1)
    assert len(calls) == 2


def test_pr_requeue():
    fb = FakeBackend()
    cid = fb.add_card("acme.ai")
    fb.add_pr_request(cid, "no_board", last_reason="board_empty")
    c = _client(fb)
    assert c.pr_requeue(cid)["status"] == "queued"
    assert json.loads(fb.requests[-1].content) == {}
    with pytest.raises(BackendError) as e:
        c.pr_requeue(cid)
    assert e.value.status == 409
    with pytest.raises(PrRequestNotFound):
        c.pr_requeue(cid + 1)


def test_pr_requests_passes_statuses_and_limit():
    fb = FakeBackend()
    a, b = fb.add_card("a.ai"), fb.add_card("b.ai")
    fb.add_pr_request(a, "open", pr_url=PR_URL, pr_number=9)
    fb.add_pr_request(b, "queued")
    c = _client(fb)
    rows = c.pr_requests(statuses=("open", "open"), limit=500)
    assert [(r["card_id"], r["domain"]) for r in rows] == [(a, "a.ai")]
    params = fb.requests[-1].url.params
    assert params.get_list("status") == ["open"] and params["limit"] == "500"
    assert [r["card_id"] for r in c.pr_requests()] == [a, b]
    assert "status" not in fb.requests[-1].url.params and fb.requests[-1].url.params["limit"] == "100"
