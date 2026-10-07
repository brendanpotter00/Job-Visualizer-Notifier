"""``radar.py refresh``: re-research cards with no leaders against the fake SDK and backend.

Covers: selection (``--missing-talent``, ``--domains``, cards with FindAll leaders skipped,
already-refreshed cards skipped, archived cards only with ``--include-archived``),
reserve-before-every-billed-call, the rebuilt payload (new brief + founders' pedigree,
rescored; event, team tally and ATS kept) and its PUT,
a 402 stop and a deadline stop that both resume without paying twice, a failed brief that
leaves the card alone, a card deleted meanwhile, and the dry run.
"""

from collections import Counter
from datetime import datetime, timezone

import httpx
import pytest
from launch_radar import radar
from launch_radar.backend_client import BackendClient
from launch_radar.card import build_payload
from launch_radar.pipeline import EXIT_BUDGET, EXIT_INCOMPLETE, EXIT_OK, Deps
from launch_radar.refresh import RefreshOptions, refresh
from launch_radar.state import StateStore
from tests.unit.launch_radar_fakes import FakeBackend, FakeParallel, candidate

NOW = datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc)
STEP_FOR_CALL = {"task_run.create(brief)": "task_run.create(brief)", "task_group.create": "task_group(pedigree)"}
ATS = {"provider": "ashby", "board_token": "Graph", "board_url": "https://jobs.ashbyhq.com/Graph", "verified": True,
       "job_count": 4, "checked_url": "https://api.ashbyhq.com/posting-api/job-board/Graph"}
OLD_BRIEF = {
    "one_liner": "Old one-liner", "website_url": "https://www.graph.ai", "what_they_do": "Old.",
    "latest_round": {"stage": "Seed", "amount_usd": "$4M", "announced_at": "2026-09-02", "lead_investors": [],
                     "other_investors": []},
    "prior_rounds": [], "total_raised_usd": "$4M",
    "latest_announcement": {"headline": "Graph raises $4M", "url": None, "announced_at": None, "kind": "funding"},
    "notable_facts": ["old fact"], "blurb": "old", "careers_url": "https://graph.ai/careers",
    "ats": {"provider": "ashby", "board_token": "Graph", "board_url": None},
}
NEW_BRIEF = {
    **OLD_BRIEF, "one_liner": "Safety graphs for AI agents", "what_they_do": "New.",
    "latest_round": {"stage": "Seed", "amount_usd": "$12M", "announced_at": "2026-09-02",
                     "lead_investors": ["Sequoia"], "other_investors": ["Y Combinator"]},
    "founders": [
        {"name": "Sam Rivera", "title": "Co-Founder & CEO", "linkedin_url": "https://www.linkedin.com/in/sam-rivera"},
        {"name": "Priya Raman", "title": "Co-Founder & CTO", "linkedin_url": None},
        {"name": "SAM RIVERA", "title": "CEO", "linkedin_url": None},
    ],
}
EVENT = {"event_type": "funding", "headline": "Graph Safety raises $4M seed", "source_url": "https://tech.eu/graph",
         "announced_at": "2026-09-02", "round": "Seed", "amount_usd": "$4M", "investors": None,
         "origin": "findall_backfill"}
TEAM = {"profiles_found": 3, "team_size_estimate": "5-10", "schools": [{"name": "MIT", "count": 1}],
        "prior_employers": [], "ex_founders_with_exit": 0, "sample_names": ["A B"]}


def card_payload(domain: str, *, leaders=(), dropped=2, issues=("no leaders confirmed; 2 company page(s) dropped",
                                                                "team tally failed: timeout")):
    """A stored card as the loop posted it (``build_payload``)."""
    return build_payload(
        company=domain.split(".")[0].title(), domain=domain, monitor_event=EVENT, brief=OLD_BRIEF, brief_basis=[],
        leaders=list(leaders), leaders_dropped=dropped, team=TEAM, ats=ATS,
        run_ids={"findall_id": "findall_old", "brief_run_id": "trun_old", "team_run_id": "trun_team",
                 "pedigree_group_id": None},
        cost_usd=0.225, timings={"findall_s": 70.0, "brief_s": 100.0, "team_s": 150.0}, issues=list(issues),
        generated_at="2026-10-07T01:00:00Z")


class Env:
    def __init__(self, tmp_path):
        self.journal: list = []
        self.fb = FakeBackend(self.journal)
        self.p = FakeParallel(self.journal)
        self.t = [0.0]
        self.logs: list[str] = []
        self.store = StateStore(tmp_path / "state")
        self.p.brief_content = NEW_BRIEF
        self.p.pedigree_by_name = {
            "Sam Rivera": ({"current_title": "CEO", "education": [{"school": "Stanford", "degree": "BS", "field": "CS",
                                                                   "grad_year": None}],
                            "prior_roles": [{"company": "Stripe", "title": "Engineer", "years": None}],
                            "founded_before": [], "years_experience": "12"},
                           {"education": "high", "prior_roles": "high", "years_experience": "high"}),
            "Priya Raman": ({"current_title": "CTO", "education": [], "prior_roles": [], "founded_before": []}, {}),
        }
        self.add_card("graph.ai", 9)

    def add_card(self, domain, card_id, *, status="new", **kw):
        self.fb.cards[domain] = {"id": card_id, "status": status, "payload": card_payload(domain, **kw),
                                 "tracked_company_id": None, "pr_url": None}

    def deps(self):
        backend = BackendClient("http://backend.test", "k", transport=self.fb.transport())
        return Deps(backend=backend, make_client=lambda: self.p, store=self.store, log=self.logs.append,
                    sleep=lambda s: self.t.__setitem__(0, self.t[0] + s), now=lambda: NOW,
                    clock=lambda: self.t[0], wall=lambda: 1000.0 + self.t[0], host="test-host")

    def refresh(self, **opts):
        opts.setdefault("missing_talent", not opts.get("domains"))
        return refresh(RefreshOptions(**opts), self.deps())

    def billed(self):
        return Counter(k for _, k, _ in self.p.billed_calls())

    def steps(self):
        return Counter(s["step"] for s in self.fb.spend)

    def assert_reserved_before_billed(self):
        reserved: Counter = Counter()
        used: Counter = Counter()
        for src, kind, val in self.journal:
            if src == "backend" and kind == "reserve":
                reserved[val] += 1
            elif src == "parallel" and kind in STEP_FOR_CALL:
                used[STEP_FOR_CALL[kind]] += 1
                assert used[STEP_FOR_CALL[kind]] <= reserved[STEP_FOR_CALL[kind]], f"{kind} without a reservation"


def test_missing_talent_refresh_rebuilds_leaders_and_scores_and_puts_the_payload(tmp_path):
    env = Env(tmp_path)
    old = env.fb.cards["graph.ai"]["payload"]
    env.add_card("people.ai", 10, leaders=[(candidate("Ana Ito", "https://linkedin.com/in/ana"), None)], dropped=0)
    env.fb.cards["people.ai"]["payload"]["scores"]["talent"] = 30  # scored: never selected
    env.add_card("has-leaders.ai", 11, leaders=[(candidate("Bo Li", "https://linkedin.com/in/bo"), None)])
    env.add_card("deleted.ai", 12, status="deleted")

    assert env.refresh() == EXIT_OK
    env.assert_reserved_before_billed()
    assert env.billed() == Counter({"task_run.create(brief)": 1, "task_group.create": 1})
    assert [j[2] for j in env.journal if j[:2] == ("backend", "put_payload")] == ["graph.ai"]
    new = env.fb.cards["graph.ai"]["payload"]
    # Leaders: the brief's founders (deduped), researched by the pedigree Task Group.
    assert [ld["name"] for ld in new["leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert new["leaders"][0]["linkedin_url"] == "https://www.linkedin.com/in/sam-rivera"
    assert new["leaders"][0]["title"] == "CEO" and new["leaders"][1]["title"] == "CTO"
    add = next(r for k, r in env.p.requests if k == "task_group.add_runs")
    assert [i["input"]["person_name"] for i in add["inputs"]] == ["Sam Rivera", "Priya Raman"]
    # Rescored from the new data.
    # Stanford 8 + Stripe 10 + 10+ years 5, all high confidence.
    assert new["scores"]["talent"] == 23 and any("Stanford" in r for r in new["scores"]["talent_reasons"])
    assert new["scores"]["vc"] is not None and new["scores"]["vc"] > (old["scores"]["vc"] or 0)
    assert new["one_liner"] == "Safety graphs for AI agents"
    # Kept from the card.
    for key in ("event", "team_stats", "ats", "pr_ready", "leaders_dropped", "company", "domain"):
        assert new[key] == old[key], key
    assert new["parallel_run_ids"] == {"findall_id": "findall_old", "brief_run_id": "trun_1",
                                       "team_run_id": "trun_team", "pedigree_group_id": "tgrp_1"}
    assert new["cost_usd"] == pytest.approx(0.225 + 0.025 + 0.02)
    assert new["timings_s"]["findall_s"] == 70.0 and "pedigree_s" in new["timings_s"]
    assert new["issues"] == ["team tally failed: timeout",
                             "leaders from the brief (FindAll found none); 2 company page(s) dropped"]
    assert new["generated_at"] == "2026-10-08T07:00:00Z"
    # Bookkeeping: one backend run, no card posted, the refresh recorded, no state left.
    (run_row,) = env.fb.runs.values()
    assert run_row["status"] == "ok" and run_row["cards_posted"] == 0 and "refreshed 1" in run_row["notes"]
    assert env.steps() == Counter({"task_run.create(brief)": 1, "task_group(pedigree)": 1})
    assert {s["domain"] for s in env.fb.spend} == {"graph.ai"}
    assert env.store.load_refresh_done()["graph.ai"]["outcome"] == "refreshed"
    assert env.store.refresh_domains() == []
    assert any("skip has-leaders.ai: has 1 leader(s) from FindAll" in m for m in env.logs)
    assert env.fb.cards["people.ai"]["payload"]["scores"]["talent"] == 30


def test_explicit_domains_and_unknown_domains(tmp_path):
    env = Env(tmp_path)
    env.add_card("other.ai", 10)
    assert env.refresh(domains=frozenset({"graph.ai", "nope.ai"})) == EXIT_OK
    assert [j[2] for j in env.journal if j[:2] == ("backend", "put_payload")] == ["graph.ai"]
    assert env.fb.cards["other.ai"]["payload"]["leaders"] == []  # not asked for
    assert any("skip nope.ai: no new or saved card" in m for m in env.logs)


def test_a_finished_refresh_is_never_bought_again(tmp_path):
    env = Env(tmp_path)
    env.p.brief_content = {**NEW_BRIEF, "founders": []}  # the brief names nobody: talent stays null
    assert env.refresh() == EXIT_OK
    new = env.fb.cards["graph.ai"]["payload"]
    assert new["leaders"] == [] and new["scores"]["talent"] is None
    assert "no leaders confirmed; 2 company page(s) dropped" in new["issues"]
    assert env.billed() == Counter({"task_run.create(brief)": 1})

    runs_before = len(env.fb.runs)
    assert env.refresh() == EXIT_OK  # still talent-null, but already refreshed
    assert env.refresh(domains=frozenset({"graph.ai"})) == EXIT_OK
    assert env.billed() == Counter({"task_run.create(brief)": 1})
    assert len(env.fb.runs) == runs_before  # nothing to do: no backend run opened
    assert any("skip graph.ai: refreshed at" in m for m in env.logs)


def test_budget_refusal_stops_and_resume_never_pays_twice(tmp_path):
    env = Env(tmp_path)
    env.add_card("other.ai", 10)
    # $0.03 covers graph.ai's brief ($0.025) but not other.ai's brief or graph.ai's pedigree ($0.02).
    assert env.refresh(budget=0.03) == EXIT_BUDGET
    env.assert_reserved_before_billed()
    assert env.billed() == Counter({"task_run.create(brief)": 1})
    assert ("backend", "refused", "task_run.create(brief)") in env.journal
    assert ("backend", "refused", "task_group(pedigree)") in env.journal
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"
    assert env.store.refresh_domains() == ["graph.ai"]  # paid-for brief kept; other.ai never started
    assert not any(j[:2] == ("backend", "put_payload") for j in env.journal)

    assert env.refresh(budget=1.0) == EXIT_OK
    env.assert_reserved_before_billed()
    assert env.billed() == Counter({"task_run.create(brief)": 2, "task_group.create": 2})
    assert env.steps() == Counter({"task_run.create(brief)": 2, "task_group(pedigree)": 2})
    assert Counter(s["domain"] for s in env.fb.spend if s["step"] == "task_run.create(brief)") == Counter(
        {"graph.ai": 1, "other.ai": 1})
    for dom in ("graph.ai", "other.ai"):
        assert [ld["name"] for ld in env.fb.cards[dom]["payload"]["leaders"]] == ["Sam Rivera", "Priya Raman"]
    assert env.fb.cards["graph.ai"]["payload"]["cost_usd"] == pytest.approx(0.27)
    assert env.store.refresh_domains() == []


def test_deadline_saves_state_and_the_next_run_resumes(tmp_path):
    env = Env(tmp_path)
    env.p.task_408s = 50  # the brief is still running...
    env.p.on_408 = lambda: env.t.__setitem__(0, env.t[0] + 60)  # ...for 60 s per long-poll
    assert env.refresh(deadline_s=200) == EXIT_INCOMPLETE
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"
    st = env.store.load_refresh("graph.ai")
    assert st["ids"] == {"brief_run_id": "trun_1"} and st["card"]["id"] == 9
    assert not any(j[:2] == ("backend", "put_payload") for j in env.journal)

    env.p.task_run.pending_408["trun_1"] = 0  # the brief has finished
    env.fb.cards["graph.ai"]["payload"]["scores"]["talent"] = 1  # no longer selected: it resumes anyway
    assert env.refresh() == EXIT_OK
    env.assert_reserved_before_billed()
    assert env.billed() == Counter({"task_run.create(brief)": 1, "task_group.create": 1})
    assert env.steps()["task_run.create(brief)"] == 1
    assert [ld["name"] for ld in env.fb.cards["graph.ai"]["payload"]["leaders"]] == ["Sam Rivera", "Priya Raman"]


def test_pedigree_runs_accepted_before_a_dropped_connection_are_not_added_twice(tmp_path):
    """The refresh reaches the same add_runs guard as ``run``: the group is asked first."""
    env = Env(tmp_path)
    real = env.p.task_group.add_runs
    calls = {"n": 0}

    def add_runs(gid, inputs, default_task_spec):
        calls["n"] += 1
        real(gid, inputs=inputs, default_task_spec=default_task_spec)
        if calls["n"] == 1:
            raise ConnectionError("read timeout")  # Parallel took the runs; the response was lost

    env.p.task_group.add_runs = add_runs
    assert env.refresh() == 1  # EXIT_ERROR: the card keeps its refresh state
    assert env.refresh() == EXIT_OK
    assert calls["n"] == 1
    assert env.steps() == Counter({"task_run.create(brief)": 1, "task_group(pedigree)": 1})
    assert [ld["name"] for ld in env.fb.cards["graph.ai"]["payload"]["leaders"]] == ["Sam Rivera", "Priya Raman"]


def test_a_failed_brief_leaves_the_card_unchanged(tmp_path):
    env = Env(tmp_path)
    before = env.fb.cards["graph.ai"]["payload"]
    env.p.task_failures = {"brief"}
    assert env.refresh() == EXIT_OK
    assert env.fb.cards["graph.ai"]["payload"] is before
    assert not any(j[:2] == ("backend", "put_payload") for j in env.journal)
    assert env.billed() == Counter({"task_run.create(brief)": 1})
    assert env.store.load_refresh_done()["graph.ai"]["outcome"] == "unchanged"
    assert any(m.startswith("unchanged") and "graph.ai" in m for m in env.logs)


def test_a_card_deleted_meanwhile_is_reported_not_an_error(tmp_path):
    env = Env(tmp_path)
    original = env.fb.handle

    def handler(request):
        if request.method == "PUT" and request.url.path.endswith("/payload"):
            return httpx.Response(404, json={"detail": "card not found"})
        return original(request)

    env.fb.handle = handler
    assert env.refresh() == EXIT_OK
    assert env.store.load_refresh_done()["graph.ai"]["outcome"] == "gone"
    assert any(m.startswith("gone") and "card 9 was deleted" in m for m in env.logs)


def test_dry_run_lists_cards_and_cost_and_spends_nothing(tmp_path):
    env = Env(tmp_path)
    env.add_card("other.ai", 10, status="saved")
    assert env.refresh(dry_run=True) == EXIT_OK
    assert env.fb.runs == {} and env.fb.spend == [] and env.billed() == Counter()
    assert not any(r.method != "GET" for r in env.fb.requests)
    assert not (tmp_path / "state").exists()
    assert any("would refresh: graph.ai (card 9, new)" in m for m in env.logs)
    assert any("would refresh: other.ai (card 10, saved)" in m for m in env.logs)
    summary = next(m for m in env.logs if m.startswith("dry run: 2 card(s)"))
    assert "at least $0.050" in summary and "about $0.110" in summary and "at most $0.210" in summary


def test_archived_cards_are_skipped_unless_include_archived(tmp_path):
    env = Env(tmp_path)
    env.add_card("shelved.ai", 10, status="archived")
    assert env.refresh(dry_run=True) == EXIT_OK
    assert {frozenset(q["statuses"]) for q in env.fb.card_queries} == {frozenset({"new", "saved"})}
    assert not any("shelved.ai" in m for m in env.logs)
    assert env.refresh(domains=frozenset({"shelved.ai"}), dry_run=True) == EXIT_OK
    assert any("skip shelved.ai: no new or saved card (an archived one needs --include-archived)" in m
               for m in env.logs)

    env.logs.clear()
    assert env.refresh(dry_run=True, include_archived=True) == EXIT_OK
    assert env.fb.card_queries[-1]["statuses"] == {"new", "saved", "archived"}
    assert any("would refresh: shelved.ai (card 10, archived)" in m for m in env.logs)
    assert radar.build_parser().parse_args(["refresh", "--missing-talent", "--include-archived"]).include_archived


def test_selection_pages_past_cards_already_refreshed(tmp_path, monkeypatch):
    from launch_radar import backend_client

    monkeypatch.setattr(backend_client, "CARDS_LIMIT", 2)
    env = Env(tmp_path)
    for i, dom in enumerate(("b.ai", "c.ai", "d.ai", "e.ai"), start=10):
        env.add_card(dom, i)
    # The first page (graph.ai, b.ai) is all done: a single capped page would select nothing.
    for dom in ("graph.ai", "b.ai"):
        env.store.mark_refresh_done(dom, {"card_id": 0, "outcome": "refreshed", "talent": None, "at": "x"})
    assert env.refresh(dry_run=True) == EXIT_OK
    assert [q["after_id"] for q in env.fb.card_queries] == [0, 10, 12]
    assert all(q["limit"] == 2 for q in env.fb.card_queries)
    would = sorted(m.split()[2] for m in env.logs if m.startswith("would refresh:"))
    assert would == ["c.ai", "d.ai", "e.ai"]


def test_a_kept_event_date_is_normalized_for_the_backend(tmp_path):
    env = Env(tmp_path)
    env.fb.cards["graph.ai"]["payload"]["event"]["announced_at"] = "September 2, 2026"  # posted before the rule
    assert env.refresh() == EXIT_OK
    event = env.fb.cards["graph.ai"]["payload"]["event"]
    assert event["announced_at"] == "2026-09-02" and event["headline"] == "Graph Safety raises $4M seed"


def test_cli_refresh_dry_run_and_argument_rules(tmp_path):
    env = Env(tmp_path)
    assert radar.main(["refresh", "--missing-talent", "--dry-run"], deps=env.deps()) == EXIT_OK
    assert any("would refresh: graph.ai" in m for m in env.logs)
    for argv in (["refresh"], ["refresh", "--missing-talent", "--domains", "a.ai"],
                 ["refresh", "--domains", "localhost"], ["refresh", "--missing-talent", "--budget", "6"]):
        with pytest.raises(SystemExit):
            radar.build_parser().parse_args(argv)
    args = radar.build_parser().parse_args(["refresh", "--domains", "https://www.Graph.ai/x, other.ai"])
    assert args.domains == frozenset({"graph.ai", "other.ai"}) and not args.missing_talent
