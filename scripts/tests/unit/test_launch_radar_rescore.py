"""``radar.py rescore``: recompute stored cards' scores for free, against the fake backend.

Covers: a legacy card (raw 0-94 Talent, no breakdown) becomes a blended card with today's
leader points carried exactly; a blended card and a second run are no-ops (no PUT); VC is
reproduced from the stored funding; ``--dry-run`` writes nothing; a card deleted meanwhile
is counted, another backend error exits 1 after the summary; ``--all`` pages every live
status; no Parallel client, backend run or reservation is ever made.
"""

import httpx
import pytest
from launch_radar import backend_client, radar
from launch_radar.backend_client import BackendClient
from launch_radar.card import build_payload
from launch_radar.pipeline import EXIT_ERROR, EXIT_OK, Deps
from launch_radar.rescore import RescoreOptions, rescore
from launch_radar.scoring import leaders_part, score_talent
from launch_radar.state import StateStore
from tests.unit.launch_radar_fakes import FakeBackend, candidate

ATS = {"provider": "ashby", "board_token": "Light", "board_url": "https://jobs.ashbyhq.com/Light", "verified": True,
       "job_count": 4, "checked_url": "https://api.ashbyhq.com/posting-api/job-board/Light"}
BRIEF = {"one_liner": "CRM", "latest_round": {"stage": "Series A", "amount_usd": "$35M", "announced_at": "2026-09-17",
                                              "lead_investors": ["CRV"], "other_investors": ["Lightspeed"]},
         "prior_rounds": [{"stage": "Seed", "amount_usd": "$5M", "investors": "Y Combinator, SV Angel"}]}
TEAM = {"profiles_found": 33, "team_size_estimate": "50-100",
        "schools": [{"name": "Stanford University", "count": 10}, {"name": "MIT", "count": 5},
                    {"name": "State University", "count": 4}],
        "prior_employers": [{"name": "Google", "count": 6}, {"name": "Stripe", "count": 3},
                            {"name": "Acme", "count": 10}],
        "sample_names": ["A B"]}
PEDIGREE = {"content": {"education": [{"school": "Stanford", "degree": "BS", "field": "CS"}],
                        "prior_roles": [{"company": "Stripe", "title": "Engineer"}],
                        "founded_before": [{"company": "Ledgerline", "outcome": "acquired", "acquirer": "Northwind"}],
                        "years_experience": 12},
            "confidence": {"education": "high", "prior_roles": "medium", "founded_before": "low",
                           "years_experience": "high"}}
EVENT = {"event_type": "funding", "headline": "Light raises $35M", "source_url": "https://tech.eu/light",
         "announced_at": "2026-09-17", "round": "Series A", "amount_usd": "$35M", "investors": None,
         "origin": "monitor"}


def blended_payload(domain: str, *, team=TEAM, leaders=True) -> dict:
    return build_payload(
        company=domain.split(".")[0].title(), domain=domain, monitor_event=EVENT, brief=BRIEF, brief_basis=[],
        leaders=[(candidate("Ada Byron", "https://linkedin.com/in/ada"), PEDIGREE)] if leaders else [],
        leaders_dropped=0, team=team, ats=ATS, run_ids={"findall_id": "f", "brief_run_id": "b", "team_run_id": "t",
                                                        "pedigree_group_id": "g"},
        cost_usd=0.3, timings={"brief_s": 10.0}, issues=[], generated_at="2026-10-07T01:00:00Z")


def legacy_payload(domain: str, **kw) -> dict:
    """The same card as the loop stored it before the blend: raw 0-94 Talent, four score keys, and
    the team tally's old ``ex_founders_with_exit`` count (no longer asked for, and ignored)."""
    p = blended_payload(domain, **kw)
    if p["team_stats"] is not None:
        p["team_stats"]["ex_founders_with_exit"] = 1
    s = p["scores"]
    raw = score_talent([{"name": "Ada Byron", "schools": ["Stanford BS CS"], "prior_companies": ["Stripe (Engineer)"],
                         "founded_raw": PEDIGREE["content"]["founded_before"], "years": 12,
                         "confidence": PEDIGREE["confidence"]}])[0] if kw.get("leaders", True) else None
    p["scores"] = {"talent": raw, "vc": s["vc"], "talent_reasons": s["talent_reasons"], "vc_reasons": s["vc_reasons"]}
    return p


class Env:
    def __init__(self, tmp_path):
        self.journal: list = []
        self.fb = FakeBackend(self.journal)
        self.logs: list[str] = []
        self.store = StateStore(tmp_path / "state")
        self.put_status: dict[int, int] = {}  # card id -> HTTP status a PUT answers instead of the fake

    def add(self, domain, card_id, payload, status="new"):
        self.fb.cards[domain] = {"id": card_id, "status": status, "payload": payload, "tracked_company_id": None}

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            card_id = int(request.url.path.split("/")[-2])
            if card_id in self.put_status:
                return httpx.Response(self.put_status[card_id], json={"detail": "nope"})
        return self.fb.handle(request)

    def deps(self):
        def no_parallel():
            raise AssertionError("rescore must never build a Parallel client")

        backend = BackendClient("http://backend.test", "k", transport=httpx.MockTransport(self._handle))
        return Deps(backend=backend, make_client=no_parallel, store=self.store, log=self.logs.append)

    def rescore(self, **opts):
        opts.setdefault("all_cards", not opts.get("domains"))
        return rescore(RescoreOptions(**opts), self.deps())

    def puts(self):
        return [j[2] for j in self.journal if j[:2] == ("backend", "put_payload")]

    def assert_free(self):
        assert self.fb.runs == {} and self.fb.spend == []
        assert not any(r.method == "POST" for r in self.fb.requests)


def test_legacy_card_becomes_blended_with_todays_leader_points_carried_exactly(tmp_path):
    env = Env(tmp_path)
    old = legacy_payload("light.ai")
    env.add("light.ai", 7, old)
    raw = old["scores"]["talent"]
    # Stanford high 8 + Stripe medium 8 + exit low 7.5 + 10+ years 5 = 28.5 -> 28 (score_talent's own rounding).
    assert raw == 28

    assert env.rescore() == EXIT_OK
    env.assert_free()
    assert env.puts() == ["light.ai"]
    new = env.fb.cards["light.ai"]["payload"]
    s = new["scores"]
    assert s["talent_leaders"] == leaders_part(raw) == 15
    assert s["talent_reasons"] == old["scores"]["talent_reasons"]  # carried verbatim
    # Schools 25 * (15/33) / (1/2) = 22.7 -> 23; employers 25 * (9/33) / (1/2) = 13.6 -> 14. The stored
    # ex_founders_with_exit is ignored: prior exits are a leaders' signal, not the team's.
    assert (s["talent_team"], s["talent"], s["talent_basis"]) == (37, 52, "both")
    assert s["talent_team_reasons"] == ["15 of the 19 schools listed across 33 profiles are top schools (+23)",
                                        "9 of the 19 employers listed across 33 profiles are top employers (+14)"]
    # VC reproduced from the stored funding block, score and reasons.
    assert (s["vc"], s["vc_reasons"]) == (old["scores"]["vc"], old["scores"]["vc_reasons"])
    # Nothing but the scores changed.
    assert {k: v for k, v in new.items() if k != "scores"} == {k: v for k, v in old.items() if k != "scores"}
    # The same card built today scores the same: a rescore converges on what the pipeline writes.
    assert s == blended_payload("light.ai")["scores"]
    assert "updated card 7 Light: talent 28→52 (leaders 15 + team 37), vc 60→60" in env.logs
    assert env.logs[-1] == "rescore: changed 1, unchanged 0, gone 0, errors 0"


def test_blended_card_and_a_second_run_are_no_ops(tmp_path):
    env = Env(tmp_path)
    env.add("light.ai", 7, blended_payload("light.ai"))
    env.add("old.ai", 8, legacy_payload("old.ai"))
    assert env.rescore() == EXIT_OK
    assert env.puts() == ["old.ai"]
    assert env.rescore() == EXIT_OK
    assert env.puts() == ["old.ai"]  # nothing new written
    assert env.logs[-1] == "rescore: changed 0, unchanged 2, gone 0, errors 0"
    env.assert_free()


def test_lone_parts_are_doubled_and_no_data_stays_null(tmp_path):
    env = Env(tmp_path)
    env.add("leaders.ai", 1, legacy_payload("leaders.ai", team={**TEAM, "profiles_found": 0}))
    env.add("team.ai", 2, legacy_payload("team.ai", leaders=False))
    env.add("none.ai", 3, legacy_payload("none.ai", leaders=False, team=None))
    assert env.rescore() == EXIT_OK
    s = {d: env.fb.cards[d]["payload"]["scores"] for d in ("leaders.ai", "team.ai", "none.ai")}
    assert (s["leaders.ai"]["talent"], s["leaders.ai"]["talent_basis"]) == (30, "leaders")
    assert (s["team.ai"]["talent"], s["team.ai"]["talent_basis"]) == (74, "team")
    assert (s["none.ai"]["talent"], s["none.ai"]["talent_basis"]) == (None, None)
    assert env.puts() == ["leaders.ai", "team.ai", "none.ai"]  # none.ai gains its (null) breakdown fields
    assert any("Leaders: talent 28→30 (leaders 15, doubled: no team data)" in m for m in env.logs)
    assert any("Team: talent -→74 (team 37, doubled: no leader data)" in m for m in env.logs)


def test_dry_run_prints_the_changes_and_writes_nothing(tmp_path):
    env = Env(tmp_path)
    old = legacy_payload("light.ai")
    env.add("light.ai", 7, old)
    assert env.rescore(dry_run=True) == EXIT_OK
    assert env.puts() == [] and env.fb.cards["light.ai"]["payload"] is old and "talent_basis" not in old["scores"]
    assert not any(r.method == "PUT" for r in env.fb.requests)
    env.assert_free()
    assert "would update card 7 Light: talent 28→52 (leaders 15 + team 37), vc 60→60" in env.logs
    assert env.logs[-1] == "rescore (dry run, nothing written): would change 1, unchanged 0, gone 0, errors 0"


def test_old_event_dates_are_normalized_on_the_put(tmp_path):
    env = Env(tmp_path)
    old = legacy_payload("light.ai")
    old["event"]["announced_at"] = "September 17, 2026"
    env.add("light.ai", 7, old)
    assert env.rescore() == EXIT_OK
    assert env.fb.cards["light.ai"]["payload"]["event"]["announced_at"] == "2026-09-17"


def test_a_deleted_card_is_counted_and_another_error_exits_1_after_the_summary(tmp_path):
    env = Env(tmp_path)
    env.add("gone.ai", 1, legacy_payload("gone.ai"))
    env.add("broken.ai", 2, legacy_payload("broken.ai"))
    env.add("fine.ai", 3, legacy_payload("fine.ai"))
    env.put_status = {1: 404, 2: 500}
    assert env.rescore() == EXIT_ERROR
    assert env.puts() == ["fine.ai"]  # the error did not stop the cards after it
    assert any(m.startswith("gone      card 1 Gone") for m in env.logs)
    assert any(m.startswith("error     card 2 Broken") and "500" in m for m in env.logs)
    assert env.logs[-1] == "rescore: changed 1, unchanged 0, gone 1, errors 1"
    env.put_status = {}
    env.fb.cards["gone.ai"]["status"] = "deleted"
    assert env.rescore() == EXIT_OK  # re-running is safe: only the unwritten cards change
    assert env.puts() == ["fine.ai", "broken.ai"]


def test_all_pages_every_live_status_and_domains_select_by_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_client, "CARDS_LIMIT", 2)
    env = Env(tmp_path)
    for i, status in enumerate(("new", "saved", "archived", "new", "deleted"), start=1):
        env.add(f"c{i}.ai", i, legacy_payload(f"c{i}.ai"), status=status)
    assert env.rescore() == EXIT_OK
    assert env.puts() == ["c1.ai", "c2.ai", "c3.ai", "c4.ai"]
    assert [(q["after_id"], q["all"], q["statuses"]) for q in env.fb.card_queries] == [
        (0, True, {"new", "saved", "archived"}), (2, True, {"new", "saved", "archived"}),
        (4, True, {"new", "saved", "archived"})]
    env.add("d.ai", 9, legacy_payload("d.ai"), status="archived")
    assert env.rescore(domains=frozenset({"d.ai", "nope.ai"})) == EXIT_OK
    assert env.puts()[-1] == "d.ai" and len(env.puts()) == 5
    assert "skip nope.ai: no live card" in env.logs


def test_rescore_through_main_never_builds_a_parallel_client(tmp_path):
    env = Env(tmp_path)
    env.add("light.ai", 7, legacy_payload("light.ai"))
    assert radar.main(["rescore", "--all", "--dry-run"], deps=env.deps()) == EXIT_OK
    assert env.puts() == []
    assert radar.main(["rescore", "--domains", "light.ai"], deps=env.deps()) == EXIT_OK
    assert env.puts() == ["light.ai"]
    env.assert_free()


@pytest.mark.parametrize("opts", [{}, {"all_cards": True, "domains": frozenset({"a.ai"})}])
def test_rescore_needs_exactly_one_selector(tmp_path, opts):
    env = Env(tmp_path)
    assert rescore(RescoreOptions(**opts), env.deps()) == EXIT_ERROR
    assert env.fb.requests == []
