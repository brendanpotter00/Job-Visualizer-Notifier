"""Backend client: auth header, 402 -> BudgetExceeded, 409 -> DomainSeen, retry rules."""

import json

import httpx
import pytest

from launch_radar.backend_client import BackendClient, BackendError, BudgetExceeded, DomainSeen

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
    payload = {"domain": "raindrop.ai", "ats": {"provider": "none", "board_token": None}, "company": "R",
               "pr_ready": False}
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
