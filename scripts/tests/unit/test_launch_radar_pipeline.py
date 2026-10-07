"""End-to-end loop runs against the fake Parallel SDK and the fake backend.

Covers: reserve-before-every-billed-call, the Search API domain lookup, dedupe
(local + GET /seen), 409 on post, 402 budget stop and resume without paying twice,
the deadline and resume, transient-error retries, ambiguous creates and add_runs,
the brief-founders fallback, queue order and staleness (Monitor vs backfill items),
dry-run (no spend, no writes), and the cap floor that cancels Monitors.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import httpx
import pytest
from launch_radar.backend_client import BackendClient
from launch_radar.pipeline import (
    EXIT_BUDGET,
    EXIT_INCOMPLETE,
    EXIT_OK,
    Deps,
    RunOptions,
    monitors_cancel,
    monitors_ensure,
    run,
)
from launch_radar.state import StateStore
from tests.unit.launch_radar_fakes import (
    FakeBackend,
    FakeParallel,
    ats_transport,
    candidate,
    monitor_content,
    stream_event,
)

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/Raindrop"
STEP_FOR_CALL = {"findall.create": "findall.create", "task_run.create(brief)": "task_run.create(brief)",
                 "task_run.create(team)": "task_run.create(team)", "task_group.create": "task_group(pedigree)",
                 "monitor.create": "monitor.create"}

BRIEF = {
    "one_liner": "Monitoring for AI agents", "website_url": "https://www.raindrop.ai",
    "what_they_do": "Agent monitoring.",
    "latest_round": {"stage": "Series A", "amount_usd": "$35M", "announced_at": "2026-09-17",
                     "lead_investors": ["CRV"], "other_investors": ["Lightspeed"]},
    "prior_rounds": [], "total_raised_usd": "$50M",
    "latest_announcement": {"headline": "Raindrop raises $35M", "url": None, "announced_at": None, "kind": "funding"},
    "notable_facts": ["f1"], "blurb": "b", "careers_url": "https://raindrop.ai/careers",
    "ats": {"provider": "ashby", "board_token": "Raindrop", "board_url": None},
}
TEAM = {"profiles_found": 6.0, "team_size_estimate": "10-20", "schools": [], "prior_employers": [],
        "ex_founders_with_exit": 0.0, "sample_names": []}


class Env:
    def __init__(self, tmp_path, *, cap=5.0, events=None):
        self.journal: list = []
        self.fb = FakeBackend(self.journal, cap=cap)
        self.p = FakeParallel(self.journal)
        self.t = [0.0]
        self.logs: list[str] = []
        self.store = StateStore(tmp_path / "state")
        self.fb.add_monitor("series_a_plus", "monitor_9", charged_through="2026-10-07T07:00:00Z")
        self.p.monitor.status["monitor_9"] = "active"
        self.p.monitor.pages["monitor_9"] = [NS(events=events if events is not None else [
            stream_event("mevt_3", monitor_content("Raindrop AI", "https://www.Raindrop.ai/blog")),
            stream_event("mevt_2", monitor_content("OpenAI", "openai.com")),
            stream_event("mevt_1", monitor_content("Mystery Co", None)),
        ], next_cursor=None)]
        self.p.findall_candidates = [
            candidate("Sam Rivera", "https://linkedin.com/in/example-sam-rivera"),
            candidate("Priya Raman", "https://raindrop.ai/team"),
            candidate("Raindrop AI", "https://www.linkedin.com/company/raindrop-ai"),
            candidate("Morgan Hale", "https://x.com/andrew", matched=False),
        ]
        self.p.pedigree_by_name = {
            "Sam Rivera": ({"current_title": "CTO", "prior_roles": [{"company": "Apple", "title": None, "years": None}],
                           "education": [], "founded_before": [], "years_experience": "8"}, {"prior_roles": "high"}),
            "Priya Raman": ({"current_title": "CEO", "education": [{"school": "UC Berkeley", "degree": "BS",
                                                                            "field": "CS", "grad_year": None}]},
                                    {"education": "medium"}),
        }
        self.p.brief_content = BRIEF
        self.p.team_content = TEAM

    def deps(self, ats=None):
        backend = BackendClient("http://backend.test", "k", transport=self.fb.transport())
        return Deps(backend=backend, make_client=lambda: self.p, store=self.store, log=self.logs.append,
                    sleep=lambda s: self.t.__setitem__(0, self.t[0] + s), now=lambda: NOW,
                    clock=lambda: self.t[0], wall=lambda: 1000.0 + self.t[0],
                    ats_transport=ats or ats_transport({ASHBY: (200, {"jobs": [{"title": "x"}] * 9})}),
                    host="test-host")

    def run(self, **opts):
        return run(RunOptions(**opts), self.deps())

    def billed(self):
        return Counter(k for _, k, _ in self.p.billed_calls())

    def assert_reserved_before_billed(self):
        reserved: Counter = Counter()
        used: Counter = Counter()
        for src, kind, val in self.journal:
            if src == "backend" and kind == "reserve":
                reserved[val] += 1
            elif src == "parallel" and kind in STEP_FOR_CALL:
                step = STEP_FOR_CALL[kind]
                used[step] += 1
                assert used[step] <= reserved[step], f"{kind} called without a reservation"


def test_full_run_posts_one_card(tmp_path):
    env = Env(tmp_path)
    assert env.run() == EXIT_OK
    env.assert_reserved_before_billed()
    # search: "Mystery Co" arrives with no domain, so the run looks it up ($0.001; no match here).
    assert env.billed() == Counter({"search": 1, "findall.create": 1, "task_run.create(brief)": 1,
                                    "task_run.create(team)": 1, "task_group.create": 1})
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["domain"] == "raindrop.ai" and card["company"] == "Raindrop AI"
    assert [ld["name"] for ld in card["leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert card["leaders_dropped"] == 1
    assert card["scores"]["vc"] == 55 and card["scores"]["talent"] is not None
    assert card["event"]["origin"] == "monitor" and card["event"]["round"] == "Series A"
    assert card["ats"]["verified"] and card["pr_ready"] is True
    assert card["team_stats"]["profiles_found"] == 6
    assert card["cost_usd"] == pytest.approx(0.1 + 0.025 + 0.1 + 0.02)
    assert card["parallel_run_ids"]["pedigree_group_id"] == "tgrp_1"
    # pedigree: one base run per kept leader, joined on row_id
    add = next(r for k, r in env.p.requests if k == "task_group.add_runs")
    assert [i["input"]["person_name"] for i in add["inputs"]] == ["Sam Rivera", "Priya Raman"]
    # bookkeeping
    run_row = next(iter(env.fb.runs.values()))
    assert run_row["status"] == "ok" and run_row["cards_posted"] == 1 and run_row["events_read"] == 3
    assert env.fb.monitors["series_a_plus"]["last_event_id"] == "mevt_3"
    assert env.store.load_queue() == [] and not env.store.has_company("raindrop.ai")
    assert any("skip 'openai.com': big tech" in m or "skip openai.com: big tech" in m for m in env.logs)


def test_seen_domain_and_tracked_name_are_skipped_before_spend(tmp_path):
    env = Env(tmp_path, events=[
        stream_event("mevt_2", monitor_content("Raindrop AI", "raindrop.ai")),
        stream_event("mevt_1", monitor_content("Ashby Tracked", "tracked.io")),
    ])
    env.fb.cards["raindrop.ai"] = {"id": 4, "status": "deleted", "payload": None, "tracked_company_id": None,
                                   "pr_url": None}
    env.fb.tracked_names["ashby tracked"] = "ashby-tracked"
    assert env.run() == EXIT_OK
    assert env.billed() == Counter()
    assert not [s for s in env.fb.spend]
    assert any("card 4 exists (deleted)" in m for m in env.logs)
    assert any("already tracked as ashby-tracked" in m for m in env.logs)
    assert env.fb.monitors["series_a_plus"]["last_event_id"] == "mevt_2"


def test_409_on_post_is_a_skip_not_an_error(tmp_path):
    env = Env(tmp_path)
    original = env.fb.handle

    def handler(request):
        if request.url.path.endswith("/seen"):
            return httpx.Response(200, json={"domains": {}, "names": {}})
        return original(request)

    env.fb.handle = handler
    env.fb.cards["raindrop.ai"] = {"id": 1, "status": "archived", "payload": {}, "tracked_company_id": None,
                                   "pr_url": None}
    assert env.run() == EXIT_OK
    assert ("backend", "post_card_409", "raindrop.ai") in env.journal
    assert any(m.startswith("seen") and "raindrop.ai" in m for m in env.logs)
    assert env.store.load_queue() == [] and not env.store.has_company("raindrop.ai")
    assert next(iter(env.fb.runs.values()))["status"] == "ok"


def test_budget_refusal_stops_and_resume_never_pays_twice(tmp_path):
    env = Env(tmp_path)
    # 0.15 covers FindAll (0.10) + brief (0.025) but not the pro team tally (0.10).
    assert env.run(budget=0.15) == EXIT_BUDGET
    env.assert_reserved_before_billed()
    assert env.billed() == Counter({"search": 1, "findall.create": 1, "task_run.create(brief)": 1})
    assert ("backend", "refused", "task_run.create(team)") in env.journal
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"
    st = env.store.load_company("raindrop.ai")
    assert set(st["ids"]) == {"findall_id", "brief_run_id"}
    assert [q["domain"] for q in env.store.load_queue()] == ["raindrop.ai"]

    # Next run: resumes the saved ids; FindAll and the brief are neither re-created nor re-reserved.
    assert env.run(budget=1.0) == EXIT_OK
    env.assert_reserved_before_billed()
    # search: "Mystery Co" arrives with no domain, so the run looks it up ($0.001; no match here).
    assert env.billed() == Counter({"search": 1, "findall.create": 1, "task_run.create(brief)": 1,
                                    "task_run.create(team)": 1, "task_group.create": 1})
    steps = Counter(s["step"] for s in env.fb.spend)
    assert steps["findall.create"] == 1 and steps["task_run.create(brief)"] == 1
    assert "raindrop.ai" in env.fb.cards
    assert env.fb.cards["raindrop.ai"]["payload"]["cost_usd"] == pytest.approx(0.245)


def test_budget_stop_holds_every_company_and_never_passes_the_cap(tmp_path):
    env = Env(tmp_path, events=[stream_event(f"mevt_{i}", monitor_content(f"Co{i} Inc", f"co{i}.ai"))
                                for i in range(5)])
    env.fb.cap = 0.12  # one FindAll fits; nothing else does
    assert env.run(budget=1.0, max_companies=5) == EXIT_BUDGET
    env.assert_reserved_before_billed()
    assert env.fb.total() <= 0.12
    assert env.billed()["findall.create"] == 1
    assert env.fb.cards == {}
    assert len(env.store.load_queue()) == 5  # all kept; the one in flight resumes next time
    assert len(list((tmp_path / "state" / "companies").glob("*.json"))) == 1


def test_low_remaining_cap_cancels_before_reading_events(tmp_path):
    env = Env(tmp_path)
    env.fb.cap = 0.05
    assert env.run() == EXIT_BUDGET
    assert env.billed() == Counter() and env.store.load_queue() == []
    assert env.p.monitor.status["monitor_9"] == "cancelled"


def test_deadline_saves_state_and_next_run_resumes(tmp_path):
    env = Env(tmp_path)
    env.p.findall_active_polls = -1  # FindAll never finishes in this run
    assert env.run(deadline_s=100) == EXIT_INCOMPLETE
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"
    st = env.store.load_company("raindrop.ai")
    assert set(st["ids"]) == {"findall_id", "brief_run_id", "team_run_id"}
    assert env.billed()["task_group.create"] == 0

    env.p.findall_active_polls = None
    assert env.run(max_companies=0) == EXIT_OK  # resumed companies continue even with 0 new ones
    # search: "Mystery Co" arrives with no domain, so the run looks it up ($0.001; no match here).
    assert env.billed() == Counter({"search": 1, "findall.create": 1, "task_run.create(brief)": 1,
                                    "task_run.create(team)": 1, "task_group.create": 1})
    assert Counter(s["step"] for s in env.fb.spend)["findall.create"] == 1
    assert "raindrop.ai" in env.fb.cards


def test_max_companies_limits_new_starts(tmp_path):
    env = Env(tmp_path, events=[stream_event(f"mevt_{i}", monitor_content(f"Co{i} Inc", f"co{i}.ai"))
                                for i in range(4)])
    assert env.run(max_companies=2) == EXIT_OK
    assert env.billed()["findall.create"] == 2
    assert len(env.fb.cards) == 2 and len(env.store.load_queue()) == 2
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"  # queue not empty


def test_dry_run_spends_and_writes_nothing(tmp_path):
    env = Env(tmp_path)
    assert env.run(dry_run=True) == EXIT_OK
    assert env.fb.runs == {} and env.fb.spend == []
    assert env.billed() == Counter()
    assert not any(r.method != "GET" for r in env.fb.requests)
    assert not (tmp_path / "state" / "queue.json").exists()
    assert any("would research: raindrop.ai" in m for m in env.logs)


def test_dry_run_prices_the_search_lookup_for_events_without_a_domain(tmp_path):
    env = Env(tmp_path)  # "Mystery Co" arrives with no domain
    assert env.run(dry_run=True) == EXIT_OK
    assert env.billed() == Counter()
    assert any("1 event(s) have no domain; a real run looks them up with the Search API ($0.001 each, "
               "at most 10 per run)" in m for m in env.logs)


def test_cap_floor_cancels_monitors_and_stops(tmp_path):
    env = Env(tmp_path)
    env.fb.spend.append({"run_id": 0, "step": "old", "domain": None, "amount_usd": 4.95, "accrued": False})
    assert env.run() == EXIT_BUDGET
    assert env.p.monitor.status["monitor_9"] == "cancelled"
    assert env.fb.monitors["series_a_plus"]["status"] == "cancelled"
    assert not any(k == "monitor.events" for _, k, _ in env.journal)
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"


def test_failed_brief_still_posts_a_card_with_issues(tmp_path):
    env = Env(tmp_path)
    env.p.task_failures = {"brief"}
    assert env.run() == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["one_liner"] is None and card["scores"]["vc"] is None
    assert card["ats"]["provider"] == "none" and card["pr_ready"] is False
    assert any(i.startswith("brief failed") for i in card["issues"])
    assert card["event"]["origin"] == "monitor"


def test_no_leaders_means_no_pedigree_and_null_talent(tmp_path):
    env = Env(tmp_path)
    env.p.findall_candidates = [candidate("Raindrop AI", "https://www.linkedin.com/company/raindrop")]
    assert env.run() == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["leaders"] == [] and card["leaders_dropped"] == 1 and card["scores"]["talent"] is None
    assert env.billed()["task_group.create"] == 0
    assert "no leaders confirmed; 1 company page(s) dropped" in card["issues"]


def test_stale_queue_item_is_dropped(tmp_path):
    env = Env(tmp_path, events=[])
    env.store.save_queue([{"domain": "old.ai", "company": "Old", "event": {}, "slot": "seed",
                           "queued_at": "2026-10-01T00:00:00Z"}])
    assert env.run() == EXIT_OK
    assert env.store.load_queue() == [] and env.billed() == Counter()
    assert any("drop old.ai" in m for m in env.logs)


def test_old_backfill_queue_item_is_kept_not_dropped_as_stale(tmp_path):
    # The backfill sweep is a deliberate, already-paid one-off: its items wait in the queue
    # however long it takes to research them. Only Monitor events go stale.
    env = Env(tmp_path, events=[])
    env.store.save_queue([
        {"domain": "old.ai", "company": "Old", "event": {}, "slot": "seed", "queued_at": "2026-10-01T00:00:00Z"},
        {"domain": "swept.ai", "company": "Swept", "event": {}, "slot": "backfill",
         "queued_at": "2026-09-01T00:00:00Z"},
    ])
    assert env.run(max_companies=0) == EXIT_OK
    assert [q["domain"] for q in env.store.load_queue()] == ["swept.ai"]
    assert any("drop old.ai" in m for m in env.logs)
    assert not any("drop swept.ai" in m for m in env.logs)
    assert "dropped 1 stale" in next(iter(env.fb.runs.values()))["notes"]


def test_monitor_events_start_before_queued_backfill_items(tmp_path):
    # Three backfill items queued ahead of one Monitor event, one company a day. Backfill items
    # never go stale but a Monitor event is dropped after 3 days, so it must not wait behind them.
    env = Env(tmp_path, events=[])
    queued = "2026-10-07T06:00:00Z"
    env.store.save_queue(
        [{"domain": f"swept{i}.ai", "company": f"Swept {i}", "event": {}, "slot": "backfill", "queued_at": queued}
         for i in range(3)]
        + [{"domain": "fresh.ai", "company": "Fresh", "event": {}, "slot": "seed", "queued_at": queued}])
    researched: list[str] = []
    for day in range(1, 5):
        deps = env.deps()
        deps.now = lambda day=day: NOW + timedelta(days=day)
        before = set(env.fb.cards)
        assert run(RunOptions(max_companies=1), deps) == EXIT_OK
        researched += sorted(set(env.fb.cards) - before)
    # The Monitor event first; the backfill items after it in their queue (FIFO) order.
    assert researched == ["fresh.ai", "swept0.ai", "swept1.ai", "swept2.ai"]
    assert not any(m.startswith("drop ") for m in env.logs)
    assert env.store.load_queue() == []


def test_exclude_skips_domains(tmp_path):
    env = Env(tmp_path)
    assert env.run(exclude=frozenset({"raindrop.ai"})) == EXIT_OK
    assert env.billed() == Counter({"search": 1}) and env.fb.cards == {}


def test_monitors_ensure_and_cancel_commands(tmp_path):
    env = Env(tmp_path)
    assert monitors_ensure(env.deps()) == EXIT_OK
    env.assert_reserved_before_billed()
    assert env.billed()["monitor.create"] == 2  # series_a_plus already active
    assert {r["status"] for r in env.fb.runs.values()} == {"ok"}
    assert monitors_cancel(env.deps()) == EXIT_OK
    assert all(m["status"] == "cancelled" for m in env.fb.monitors.values())
    assert all(s == "cancelled" for s in env.p.monitor.status.values())


def test_monitors_ensure_stops_on_budget(tmp_path):
    env = Env(tmp_path)
    env.fb.monitors.clear()
    env.fb.cap = 0.015  # room for one $0.01 create, not two
    assert monitors_ensure(env.deps()) == EXIT_BUDGET
    assert env.billed()["monitor.create"] == 1
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"


# ---- transient failures, ambiguous creates, run bookkeeping ---------------------------
def test_transient_brief_error_keeps_the_company_and_the_next_run_posts_it(tmp_path):
    env = Env(tmp_path)
    env.p.task_result_errors = {"brief": [503]}
    assert env.run() == EXIT_INCOMPLETE
    assert env.fb.cards == {}
    assert env.store.load_company("raindrop.ai")["retries"] == 1
    assert "retry 1" in next(iter(env.fb.runs.values()))["notes"]

    assert env.run(max_companies=0) == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["one_liner"] == "Monitoring for AI agents" and card["scores"]["vc"] is not None
    assert env.billed()["task_run.create(brief)"] == 1  # the paid-for brief was collected, not re-bought


def test_transient_errors_post_with_an_issue_after_max_retries(tmp_path):
    from launch_radar.pipeline import MAX_RETRIES

    env = Env(tmp_path)
    env.p.task_result_errors = {"brief": [503] * (MAX_RETRIES + 1)}
    for _ in range(MAX_RETRIES):
        assert env.run(max_companies=1) == EXIT_INCOMPLETE
    assert env.run(max_companies=0) == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert any(i.startswith(f"brief not collected after {MAX_RETRIES} attempts") for i in card["issues"])


def test_ats_outage_is_retried_instead_of_posting_no_board(tmp_path):
    env = Env(tmp_path)
    down = ats_transport({ASHBY: (503, {"error": "down"})})
    assert run(RunOptions(), env.deps(ats=down)) == EXIT_INCOMPLETE
    assert env.fb.cards == {} and env.store.has_company("raindrop.ai")
    assert env.run(max_companies=0) == EXIT_OK
    assert env.fb.cards["raindrop.ai"]["payload"]["pr_ready"] is True


def test_missing_board_is_recorded_as_an_issue(tmp_path):
    env = Env(tmp_path)
    assert run(RunOptions(), env.deps(ats=ats_transport({}))) == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["pr_ready"] is False
    assert "ATS check ashby/Raindrop: HTTP 404" in card["issues"]


def test_ambiguous_create_failure_reserves_the_retry_again(tmp_path):
    env = Env(tmp_path)
    real_create = env.p.task_run.create
    calls = {"n": 0}

    def flaky_create(**req):
        if req["metadata"]["step"] == "team" and calls["n"] == 0:
            calls["n"] += 1
            raise ConnectionError("read timeout")  # may have reached Parallel
        return real_create(**req)

    env.p.task_run.create = flaky_create
    assert env.run() == 1  # EXIT_ERROR: the company errored, state kept
    assert env.run(max_companies=0) == EXIT_OK
    steps = [s["step"] for s in env.fb.spend]
    assert steps.count("task_run.create(team)") == 1 and steps.count("task_run.create(team)#retry1") == 1
    assert any("re-creating task_run.create(team)#retry1" in m for m in env.logs)


def test_refused_create_is_not_reserved_twice(tmp_path):
    from tests.unit.launch_radar_fakes import FakeAPIStatusError

    env = Env(tmp_path)
    real_create = env.p.task_run.create
    calls = {"n": 0}

    def refused(**req):
        if req["metadata"]["step"] == "team" and calls["n"] == 0:
            calls["n"] += 1
            raise FakeAPIStatusError(422)  # Parallel answered: nothing was created
        return real_create(**req)

    env.p.task_run.create = refused
    assert env.run() == 1
    assert env.run(max_companies=0) == EXIT_OK
    assert [s["step"] for s in env.fb.spend].count("task_run.create(team)") == 1
    assert not any("#retry" in s["step"] for s in env.fb.spend)


def _flaky_add_runs(env, *, first_error, accepted=False):
    """``task_group.add_runs`` whose first call raises ``first_error``; with ``accepted`` the
    runs were added before the error (the response was lost after Parallel took them)."""
    real = env.p.task_group.add_runs
    calls = {"n": 0}

    def add_runs(gid, inputs, default_task_spec):
        calls["n"] += 1
        if calls["n"] == 1:
            if accepted:
                real(gid, inputs=inputs, default_task_spec=default_task_spec)
            raise first_error
        return real(gid, inputs=inputs, default_task_spec=default_task_spec)

    env.p.task_group.add_runs = add_runs


def test_pedigree_runs_accepted_before_an_ambiguous_failure_are_not_added_again(tmp_path):
    env = Env(tmp_path)
    _flaky_add_runs(env, first_error=ConnectionError("read timeout"), accepted=True)
    assert env.run() == 1  # EXIT_ERROR: the company errored, its state is kept
    assert env.store.load_company("raindrop.ai")["attempts"]["pedigree_runs"] == 1
    assert env.run(max_companies=0) == EXIT_OK
    # The group already held the runs, so they were marked added: no second add_runs, no new reservation.
    assert sum(1 for _, k, _ in env.journal if k == "task_group.add_runs") == 1
    assert not any("#retry" in s["step"] for s in env.fb.spend)
    assert any("already holds 2 run(s)" in m for m in env.logs)
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["scores"]["talent"] is not None and not any("pedigree" in i for i in card["issues"])
    assert card["cost_usd"] == pytest.approx(0.1 + 0.025 + 0.1 + 0.02)


def test_pedigree_runs_lost_to_an_ambiguous_failure_are_reserved_again_before_the_re_add(tmp_path):
    env = Env(tmp_path)
    _flaky_add_runs(env, first_error=ConnectionError("read timeout"))
    assert env.run() == 1
    assert env.run(max_companies=0) == EXIT_OK
    steps = [s["step"] for s in env.fb.spend]
    assert steps.count("task_group(pedigree)") == 1 and steps.count("task_group(pedigree)#retry1") == 1
    retry = next(s for s in env.fb.spend if s["step"] == "task_group(pedigree)#retry1")
    assert retry["amount_usd"] == pytest.approx(0.02) and retry["domain"] == "raindrop.ai"
    # The group held no runs, so they were reserved again, THEN added once.
    assert env.journal.index(("backend", "reserve", "task_group(pedigree)#retry1")) < env.journal.index(
        ("parallel", "task_group.add_runs", 2))
    assert sum(1 for _, k, _ in env.journal if k == "task_group.add_runs") == 1
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert [ld["name"] for ld in card["leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert card["cost_usd"] == pytest.approx(0.1 + 0.025 + 0.1 + 0.02 + 0.02)
    assert any("re-adding the pedigree runs under task_group(pedigree)#retry1" in m for m in env.logs)


def test_refused_pedigree_runs_are_added_again_without_a_second_reservation(tmp_path):
    from tests.unit.launch_radar_fakes import FakeAPIStatusError

    env = Env(tmp_path)
    _flaky_add_runs(env, first_error=FakeAPIStatusError(422))  # Parallel answered: nothing was added
    assert env.run() == 1
    assert env.store.load_company("raindrop.ai")["attempts"].get("pedigree_runs", 0) == 0
    assert env.run(max_companies=0) == EXIT_OK
    assert [s["step"] for s in env.fb.spend].count("task_group(pedigree)") == 1
    assert not any("#retry" in s["step"] for s in env.fb.spend)
    assert env.fb.cards["raindrop.ai"]["payload"]["scores"]["talent"] is not None


def test_leader_missing_on_resume_keeps_pedigree_aligned(tmp_path):
    env = Env(tmp_path)
    env.p.findall_active_polls = -1
    assert env.run(deadline_s=100) == EXIT_INCOMPLETE
    st = env.store.load_company("raindrop.ai")
    st["leader_ids"] = ["cand_gone", "cand_priya_raman"]  # saved before; the first is no longer in the result
    env.store.save_company("raindrop.ai", st)
    env.p.findall_active_polls = None
    assert env.run(max_companies=0) == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert [ld["name"] for ld in card["leaders"]] == ["Priya Raman"]
    add = next(r for k, r in env.p.requests if k == "task_group.add_runs")
    assert [(i["input"]["person_name"], i["metadata"]["row_id"]) for i in add["inputs"]] == [("Priya Raman", "1")]
    assert any("leader 1 (cand_gone) missing" in i for i in card["issues"])


def test_over_cap_cancels_parallel_orphans_even_without_backend_rows(tmp_path):
    env = Env(tmp_path)
    env.fb.monitors.clear()  # backend thinks nothing is active...
    env.p.monitor.status["monitor_orphan"] = "active"  # ...but Parallel still bills one
    env.fb.spend.append({"run_id": 0, "step": "old", "domain": None, "amount_usd": 4.95, "accrued": False})
    assert env.run() == EXIT_BUDGET
    assert env.p.monitor.status["monitor_orphan"] == "cancelled"
    assert next(iter(env.fb.runs.values()))["notes"] == "spend cap reached; cancelled 2 monitor(s)"


def test_no_active_monitors_is_reported_not_ok(tmp_path):
    env = Env(tmp_path)
    env.fb.monitors.clear()
    assert env.run() == EXIT_OK
    row = next(iter(env.fb.runs.values()))
    assert row["status"] == "stopped" and "no active monitors" in row["notes"]
    assert any("no active monitors" in m for m in env.logs)


def test_stale_drops_are_counted_in_the_notes(tmp_path):
    env = Env(tmp_path, events=[])
    env.store.save_queue([{"domain": f"old{i}.ai", "company": "Old", "event": {}, "slot": "seed",
                           "queued_at": "2026-10-01T00:00:00Z"} for i in range(2)])
    assert env.run() == EXIT_OK
    assert "dropped 2 stale" in next(iter(env.fb.runs.values()))["notes"]


def test_failed_finish_does_not_hide_the_original_error(tmp_path):
    env = Env(tmp_path)
    original = env.fb.handle

    def handler(request):
        if request.url.path.endswith("/seen"):
            return httpx.Response(500, json={"detail": "seen exploded"})
        if request.url.path.endswith("/finish"):
            return httpx.Response(503, json={"detail": "backend gone"})
        return original(request)

    env.fb.handle = handler
    with pytest.raises(Exception, match="seen exploded|/seen"):
        env.run()
    assert any("could not finish run" in m for m in env.logs)
    assert any("failed:" in m and "/seen" in m for m in env.logs)


def test_event_without_domain_is_resolved_by_search_then_carded(tmp_path):
    env = Env(tmp_path, events=[stream_event("mevt_1", monitor_content("Raindrop AI", None))])
    env.p.search_results = {"Raindrop AI": [
        NS(url="https://techcrunch.com/2026/09/17/raindrop-series-a"),
        NS(url="https://www.crunchbase.com/organization/raindrop-ai"),
        NS(url="https://www.raindrop.ai/"),
    ]}
    assert env.run() == EXIT_OK
    env.assert_reserved_before_billed()
    assert env.billed()["search"] == 1
    assert "raindrop.ai" in env.fb.cards
    assert any("domain lookup: 'Raindrop AI' -> raindrop.ai" in m for m in env.logs)


def test_unresolved_event_is_skipped_without_research_spend(tmp_path):
    env = Env(tmp_path, events=[stream_event("mevt_1", monitor_content("Navra", None))])
    env.p.search_results = {"Navra": [NS(url="https://www.linkedin.com/company/navra"), NS(url="https://tech.eu/navra")]}
    assert env.run() == EXIT_OK
    assert env.billed() == Counter({"search": 1}) and env.fb.cards == {}
    assert any("skip 'Navra': no domain" in m for m in env.logs)


# ---- the leaders fallback: the brief's founders when FindAll confirms no person ---------------
FOUNDERS = [
    {"name": "Sam Rivera", "title": "Co-Founder & CEO", "linkedin_url": "https://linkedin.com/in/example-sam-rivera"},
    {"name": "sam  rivera", "title": "CEO", "linkedin_url": None},  # the same person again
    {"name": "Priya Raman", "title": "Co-Founder & CTO", "linkedin_url": "https://x.com/priya"},
    {"name": "", "title": "COO", "linkedin_url": None},
]


def _journal_results(env):
    """Record each Task /result call in the journal, so a test can see what was waited on when."""
    real = env.p.task_run.result

    def result(run_id, **kw):
        env.journal.append(("parallel", "task_run.result", env.p.task_run.step_of[run_id]))
        return real(run_id, **kw)

    env.p.task_run.result = result


def test_findall_with_no_person_falls_back_to_the_brief_founders(tmp_path):
    env = Env(tmp_path)
    env.p.findall_candidates = [candidate("Raindrop AI", "https://www.linkedin.com/company/raindrop")]
    env.p.brief_content = {**BRIEF, "founders": FOUNDERS}
    _journal_results(env)
    assert env.run() == EXIT_OK
    env.assert_reserved_before_billed()
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert [ld["name"] for ld in card["leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert card["leaders"][0]["linkedin_url"] == "https://linkedin.com/in/example-sam-rivera"
    assert card["leaders"][1]["linkedin_url"] is None  # not a LinkedIn URL
    assert card["leaders_dropped"] == 1 and card["scores"]["talent"] is not None
    assert "leaders from the brief (FindAll found none); 1 company page(s) dropped" in card["issues"]
    assert not any(i.startswith("no leaders confirmed") for i in card["issues"])
    # The pedigree ran on the founders, after the brief came back.
    add = next(r for k, r in env.p.requests if k == "task_group.add_runs")
    assert [(i["input"]["person_name"], i["input"]["current_title"]) for i in add["inputs"]] == [
        ("Sam Rivera", "Co-Founder & CEO"), ("Priya Raman", "Co-Founder & CTO")]
    kinds = [(k, v) for _, k, v in env.journal]
    assert kinds.index(("task_run.result", "brief")) < kinds.index(("task_group.create", "raindrop.ai"))
    assert Counter(s["step"] for s in env.fb.spend)["task_group(pedigree)"] == 1
    assert next(s for s in env.fb.spend if s["step"] == "task_group(pedigree)")["amount_usd"] == pytest.approx(0.02)
    assert env.billed()["task_run.create(brief)"] == 1  # the brief was waited on once, never re-bought


def test_no_fallback_when_findall_found_people(tmp_path):
    env = Env(tmp_path)
    env.p.brief_content = {**BRIEF, "founders": [{"name": "Other Founder", "title": "CEO", "linkedin_url": None}]}
    assert env.run() == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert [ld["name"] for ld in card["leaders"]] == ["Sam Rivera", "Priya Raman"]
    add = next(r for k, r in env.p.requests if k == "task_group.add_runs")
    assert "Other Founder" not in [i["input"]["person_name"] for i in add["inputs"]]
    assert not any("leaders from the brief" in i for i in card["issues"])
    assert "brief_leaders" not in (env.store.load_company("raindrop.ai") or {})


def test_fallback_caps_founders_at_the_leader_limit(tmp_path):
    env = Env(tmp_path)
    env.p.findall_candidates = []
    env.p.brief_content = {**BRIEF, "founders": [{"name": f"Person {i} Name", "title": "VP", "linkedin_url": None}
                                                 for i in range(11)]}
    assert env.run() == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert len(card["leaders"]) == 8 and card["leaders_dropped"] == 0
    assert "leaders from the brief (FindAll found none)" in card["issues"]
    assert next(s for s in env.fb.spend if s["step"] == "task_group(pedigree)")["amount_usd"] == pytest.approx(0.08)


def test_fallback_with_a_failed_brief_posts_no_leaders(tmp_path):
    env = Env(tmp_path)
    env.p.findall_candidates = []
    env.p.task_failures = {"brief"}
    assert env.run() == EXIT_OK
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert card["leaders"] == [] and card["scores"]["talent"] is None
    assert "no leaders confirmed" in card["issues"] and any(i.startswith("brief failed") for i in card["issues"])
    assert env.billed()["task_group.create"] == 0


def test_fallback_resumes_after_the_deadline_without_paying_twice(tmp_path):
    env = Env(tmp_path)
    env.p.findall_candidates = []
    env.p.brief_content = {**BRIEF, "founders": FOUNDERS}
    busy = {"on": True}
    real_retrieve = env.p.task_group.retrieve
    env.p.task_group.retrieve = lambda gid: NS(status=NS(is_active=True)) if busy["on"] else real_retrieve(gid)
    assert env.run(deadline_s=120) == EXIT_INCOMPLETE
    st = env.store.load_company("raindrop.ai")
    assert [f["name"] for f in st["brief_leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert st["ids"]["pedigree_group_id"] == "tgrp_1" and st["pedigree_runs_added"] is True

    busy["on"] = False
    env.p.brief_content = {**BRIEF, "founders": []}  # a resume uses the SAVED founders, not a re-read
    assert env.run(max_companies=0) == EXIT_OK
    env.assert_reserved_before_billed()
    card = env.fb.cards["raindrop.ai"]["payload"]
    assert [ld["name"] for ld in card["leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert env.billed()["task_group.create"] == 1 and env.billed()["task_run.create(brief)"] == 1
    assert sum(1 for _, k, _ in env.journal if k == "task_group.add_runs") == 1
    steps = Counter(s["step"] for s in env.fb.spend)
    assert steps["task_group(pedigree)"] == 1 and steps["task_run.create(brief)"] == 1
