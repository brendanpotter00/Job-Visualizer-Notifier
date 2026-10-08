"""``radar.py backfill``: one FindAll sweep of the past month into the queue.

Covers: the request shape and window dates, reserve-before-every-billed-call, the 402
stop, enrichment parsing (float casts, the window drop), dedupe and the queue append,
resume without a second paid create, dry-run (no call at all), and the card's event
block carrying the backfill origin through ``run``.
"""

from collections import Counter
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest
from launch_radar import radar
from launch_radar.backend_client import BackendClient
from launch_radar.backfill import (
    CREATE_STEP,
    ENRICH_STEP,
    ORIGIN,
    BackfillOptions,
    as_text,
    backfill,
    chunks,
    create_estimate,
    create_request,
    enrich_estimate,
    enrich_request,
    match_to_event,
    parse_date,
    run_budget,
    usd_text,
    window,
)
from launch_radar.card import build_event
from launch_radar.monitors import EVENT_FIELDS
from launch_radar.pipeline import (
    EXIT_BUDGET,
    EXIT_ERROR,
    EXIT_INCOMPLETE,
    EXIT_OK,
    Deps,
    RunOptions,
    run,
)
from launch_radar.state import StateStore
from tests.unit.launch_radar_fakes import (
    FakeBackend,
    FakeParallel,
    ats_transport,
    candidate,
    company_match,
)

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)
START, END = "2026-09-07", "2026-10-07"
BILLED_STEP = {"findall.create": CREATE_STEP, "findall.enrich": ENRICH_STEP, "search": "search("}


def enrichment(name, domain, *, etype="funding", rnd="Seed", amount="$5M", investors="Acme Ventures",
               at="2026-09-20", src=None, headline=None):
    return {"company_name": name, "company_domain": domain, "event_type": etype, "round": rnd,
            "amount_usd": amount, "investors": investors, "announced_at": at, "source_url": src,
            "headline": headline or f"{name} news"}


class Env:
    def __init__(self, tmp_path, *, cap=5.0):
        self.journal: list = []
        self.fb = FakeBackend(self.journal, cap=cap)
        self.p = FakeParallel(self.journal)
        self.t = [0.0]
        self.logs: list[str] = []
        self.store = StateStore(tmp_path / "state")
        self.p.findall_candidates = [
            company_match("Raindrop AI", "https://www.linkedin.com/company/raindrop-ai", cid="c_raindrop"),
            company_match("Navra", "navra.io", cid="c_navra", announcement_url="https://news.example.com/navra"),
            company_match("Oldco Labs", "https://oldco.ai", cid="c_old"),
            company_match("Mystery Labs", "https://www.crunchbase.com/organization/mystery-labs", cid="c_mystery"),
            company_match("OpenAI", "https://openai.com", cid="c_openai"),
            company_match("Seen Co", "https://seen.co", cid="c_seen"),
            company_match("Quiet Inc", "https://quiet.dev", cid="c_quiet"),  # never enriched
            company_match("Nope", "https://nope.ai", matched=False, cid="c_nope"),
        ]
        self.p.findall_enrichment = {
            # Parallel can return numbers for string fields, and lists for a comma-separated one.
            "c_raindrop": enrichment("Raindrop AI", "https://www.Raindrop.ai/", rnd="Series A", amount=15000000.0,
                                     investors=["CRV", "Lightspeed"], at="2026-09-17",
                                     src="https://techcrunch.com/2026/09/17/raindrop",
                                     headline="Raindrop raises $15M Series A"),
            "c_navra": enrichment("Navra", None, etype="launch", rnd=None, amount=None, investors=None,
                                  at="2026-09-30"),
            "c_old": enrichment("Oldco Labs", "oldco.ai", at="2026-08-01"),
            "c_mystery": enrichment("Mystery Labs", None, at=None),
            "c_openai": enrichment("OpenAI", "openai.com"),
            "c_seen": enrichment("Seen Co", "seen.co"),
            "c_nope": enrichment("Nope", "nope.ai"),
        }
        self.p.search_results = {"Mystery Labs": [NS(url="https://www.crunchbase.com/organization/mystery-labs"),
                                                  NS(url="https://mysterylabs.dev/")]}
        self.fb.cards["seen.co"] = {"id": 9, "status": "archived", "payload": None, "tracked_company_id": None}

    def deps(self, ats=None):
        backend = BackendClient("http://backend.test", "k", transport=self.fb.transport())
        return Deps(backend=backend, make_client=lambda: self.p, store=self.store, log=self.logs.append,
                    sleep=lambda s: self.t.__setitem__(0, self.t[0] + s), now=lambda: NOW,
                    clock=lambda: self.t[0], wall=lambda: 1000.0 + self.t[0],
                    ats_transport=ats or ats_transport({}), host="test-host")

    def backfill(self, **opts):
        return backfill(BackfillOptions(**opts), self.deps())

    def billed(self):
        return Counter(k for _, k, _ in self.p.billed_calls())

    def steps(self):
        return [s["step"] for s in self.fb.spend]

    def assert_reserved_before_billed(self):
        reserved: Counter = Counter()
        used: Counter = Counter()
        for src, kind, val in self.journal:
            if src == "backend" and kind == "reserve":
                reserved.update(call for call, prefix in BILLED_STEP.items() if val.startswith(prefix))
            elif src == "parallel" and kind in BILLED_STEP:
                used[kind] += 1
                assert used[kind] <= reserved[kind], f"{kind} called without a reservation"


# ---- requests, estimates, parsing ---------------------------------------------------------
def test_create_request_shape_and_window_dates():
    assert window(NOW, 30) == (START, END)
    assert window(datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc).astimezone(), 30) == (START, END)
    req = create_request(START, END, "base", 20)
    assert set(req) == {"objective", "entity_type", "match_conditions", "generator", "match_limit", "metadata"}
    assert req["entity_type"] == "companies" and req["generator"] == "base" and req["match_limit"] == 20
    span = "between 2026-09-07 and 2026-10-07 (inclusive)"
    assert span in req["objective"]
    names = [mc["name"] for mc in req["match_conditions"]]
    assert names == ["early_stage_startup_check", "recent_announcement_check"]
    startup, recent = (mc["description"] for mc in req["match_conditions"])
    assert "NOT a publicly traded company" in startup and "Google" in startup
    assert span in recent and "Series A" in recent and "product launch" in recent
    assert req["metadata"] == {"app": "launch-radar", "step": "backfill", "window": "2026-09-07..2026-10-07"}


def test_enrich_request_is_a_flat_monitor_shaped_schema():
    req = enrich_request(START, END)
    assert req["processor"] == "base" and req["output_schema"]["type"] == "json"
    schema = req["output_schema"]["json_schema"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert list(schema["properties"]) == list(EVENT_FIELDS) and schema["required"] == list(EVENT_FIELDS)
    assert all(p["type"] in ("string", ["string", "null"]) for p in schema["properties"].values())
    assert schema["properties"]["event_type"]["enum"] == ["funding", "launch"]
    nullable = {k for k, p in schema["properties"].items() if p["type"] == ["string", "null"]}
    assert nullable == {"company_domain", "round", "amount_usd", "investors", "announced_at", "source_url"}
    assert "2026-09-07" in schema["properties"]["announced_at"]["description"]


def test_estimates_and_reservation_chunks():
    assert create_estimate("base", 20) == 0.85 and create_estimate("preview", 10) == 0.1
    assert enrich_estimate(7) == 0.07
    assert run_budget("base", 20) == 1.15  # 0.85 + 20 x 0.01 + 20 x 0.005
    assert chunks(0.85) == [0.85] and chunks(1.0) == [1.0] and chunks(1.15) == [1.0, 0.15]
    assert chunks(2.0) == [1.0, 1.0]


def test_text_casts_numbers_and_lists():
    assert as_text(2026.0) == "2026" and as_text(3) == "3" and as_text(2.5) == "2.5"
    assert as_text(["CRV", None, " Lightspeed "]) == "CRV, Lightspeed"
    assert as_text(True) is None and as_text(float("nan")) is None and as_text("  ") is None
    assert usd_text(15000000.0) == "$15M" and usd_text(2500000) == "$2.5M" and usd_text(1.25e9) == "$1.25B"
    assert usd_text(750000.0) == "$750K" and usd_text(100.0) == "$100" and usd_text("$40M") == "$40M"
    assert usd_text(0) is None and usd_text(None) is None
    assert parse_date("2026-09-17T10:00:00Z") == date(2026, 9, 17)
    assert parse_date("September 20, 2026") == date(2026, 9, 20)
    assert parse_date("2026-09") is None and parse_date("2026-02-30") is None and parse_date(None) is None


def _enriched(cid, fields, **kw):
    cd = company_match(fields["company_name"], kw.pop("url", "https://example.org"), cid=cid, **kw)
    cd.output = {**cd.output, **{k: {"value": v, "type": "enrichment"} for k, v in fields.items()}}
    return cd


def test_match_to_event_parses_casts_and_drops_out_of_window_rows():
    lo, hi = date(2026, 9, 7), date(2026, 10, 7)
    cd = _enriched("c1", enrichment("Raindrop AI", "https://www.Raindrop.ai/x", rnd=2.0, amount=15000000.0,
                                    investors=["CRV", "Lightspeed"], at="2026-09-17T09:00:00Z",
                                    src="https://techcrunch.com/r", etype="Funding"))
    ev, reason = match_to_event(cd, lo, hi, "findall_1")
    assert reason == "" and set(EVENT_FIELDS) <= set(ev)
    assert ev["company_domain"] == "raindrop.ai" and ev["domain_source"] == "enrichment"
    assert ev["event_type"] == "funding" and ev["round"] == "2" and ev["amount_usd"] == "$15M"
    assert ev["investors"] == "CRV, Lightspeed" and ev["announced_at"] == "2026-09-17"
    assert ev["source_url"] == "https://techcrunch.com/r"
    assert (ev["origin"], ev["slot"], ev["event_id"], ev["findall_id"]) == (ORIGIN, "backfill", "c1", "findall_1")
    # window edges are inclusive; outside them the row is dropped
    for at, kept in (("2026-09-07", True), ("2026-10-07", True), ("2026-09-06", False), ("2026-10-08", False)):
        got, why = match_to_event(_enriched("c2", enrichment("X Co", "x.co", at=at)), lo, hi, "f")
        assert (got is not None) == kept and (why == "" if kept else why == "announced outside the window")
    # undated rows stay (the match condition checked the date); un-enriched rows are skipped
    undated, _ = match_to_event(_enriched("c3", enrichment("Y Co", "y.co", at=None)), lo, hi, "f")
    assert undated["announced_at"] is None and undated["event_date"] is None
    # a month alone is kept as YYYY-MM; text that is no date at all becomes None, never raw text
    monthly, _ = match_to_event(_enriched("c4", enrichment("M Co", "m.co", at="2026-09")), lo, hi, "f")
    assert monthly["announced_at"] == "2026-09" and monthly["event_date"] is None
    vague, _ = match_to_event(_enriched("c5", enrichment("V Co", "v.co", at="earlier this month")), lo, hi, "f")
    assert vague["announced_at"] is None
    assert match_to_event(company_match("Z Co", "https://z.co"), lo, hi, "f") == (None, "not enriched")


def test_directory_domain_falls_back_to_the_candidate_url_and_citation():
    lo, hi = date(2026, 9, 7), date(2026, 10, 7)
    cd = _enriched("c1", enrichment("Navra", "https://www.crunchbase.com/organization/navra", src="javascript:x"),
                   url="navra.io", announcement_url="https://news.example.com/navra")
    ev, _ = match_to_event(cd, lo, hi, "f")
    assert ev["company_domain"] == "navra.io" and ev["domain_source"] == "findall_url"
    assert ev["source_url"] == "https://news.example.com/navra"  # unsafe URL dropped, the citation used
    neither, _ = match_to_event(_enriched("c2", enrichment("Ghost", None), url="https://linkedin.com/company/g"),
                                lo, hi, "f")
    assert neither["company_domain"] is None and "domain_source" not in neither


def test_card_event_keeps_the_backfill_origin_and_announcement_fields():
    ev = {"event_type": "funding", "headline": "Raindrop raises $15M", "source_url": "https://techcrunch.com/r",
          "announced_at": "2026-09-17", "round": "Series A", "amount_usd": "$15M", "investors": "CRV",
          "origin": ORIGIN}
    assert build_event("Raindrop AI", ev, None) == {
        "type": "funding", "headline": "Raindrop raises $15M", "source_url": "https://techcrunch.com/r",
        "announced_at": "2026-09-17", "round": "Series A", "amount_usd": "$15M", "investors": "CRV",
        "origin": "findall_backfill"}
    assert build_event("X", dict(ev, origin=None), None)["origin"] == "monitor"  # a Monitor event has none
    assert build_event("X", dict(ev, origin="evil"), None)["origin"] == "monitor"


# ---- the command ----------------------------------------------------------------------------
def test_backfill_queues_the_survivors_and_reserves_before_every_billed_call(tmp_path):
    env = Env(tmp_path)
    assert env.backfill() == EXIT_OK
    env.assert_reserved_before_billed()
    assert env.billed() == Counter({"findall.create": 1, "findall.enrich": 1, "search": 1})
    # order: reserve create -> create -> reserve enrich -> enrich
    order = [(s, k) for s, k, _ in env.journal if (s, k) in {("backend", "reserve"), ("parallel", "findall.create"),
                                                             ("parallel", "findall.enrich")}]
    assert order[:4] == [("backend", "reserve"), ("parallel", "findall.create"), ("backend", "reserve"),
                         ("parallel", "findall.enrich")]
    spend = {s["step"]: s["amount_usd"] for s in env.fb.spend}
    assert spend[CREATE_STEP] == 0.85 and spend[ENRICH_STEP] == 0.07  # 7 matches x $0.01
    assert spend["search(domain:mystery labs)"] == 0.005
    # the requests Parallel received
    create = next(r for k, r in env.p.requests if k == "findall.create")
    assert create == create_request(START, END, "base", 20)
    enrich = next(r for k, r in env.p.requests if k == "findall.enrich")
    assert enrich["findall_id"] == "findall_1" and enrich["processor"] == "base"
    # the queue: best first, each with a Monitor-shaped event
    queue = env.store.load_queue()
    assert [q["domain"] for q in queue] == ["raindrop.ai", "mysterylabs.dev", "navra.io"]
    assert {q["slot"] for q in queue} == {"backfill"} and all(q["queued_at"] == "2026-10-07T07:00:00Z" for q in queue)
    rd = queue[0]["event"]
    assert (rd["origin"], rd["amount_usd"], rd["investors"], rd["round"]) == (ORIGIN, "$15M", "CRV, Lightspeed",
                                                                              "Series A")
    assert rd["source_url"] == "https://techcrunch.com/2026/09/17/raindrop" and rd["announced_at"] == "2026-09-17"
    assert queue[1]["event"]["domain_source"] == "search"
    assert queue[2]["event"]["source_url"] == "https://news.example.com/navra"
    # the backend run and the summary
    row = next(iter(env.fb.runs.values()))
    assert row["status"] == "ok" and row["events_read"] == 7 and row["budget"] == 1.15
    assert "matched 7, kept 5, queued 3" in row["notes"]
    assert any("matched 7 · kept 5 · queued 3" in m for m in env.logs)
    skipped = next(m for m in env.logs if "skipped:" in m)
    for reason in ("not enriched 1", "announced outside the window 1", "big tech 1", "card exists 1"):
        assert reason in skipped
    # $0.25 + 7 x $0.03 + 7 x $0.01 + 1 x $0.005; reserved $0.85 + $0.07 + $0.005
    assert any("spend (estimate)" in m and "1 domain lookup(s) x $0.005 = $0.535 (reserved $0.925)" in m
               for m in env.logs)
    assert "queued: navra.io (Navra) launch 2026-09-30" in env.logs
    st = env.store.load_backfill()
    assert st["findall_id"] == "findall_1" and st["finished_at"] and st["summary"]["queued"] == 3


def test_402_on_the_create_stops_before_any_parallel_call(tmp_path):
    env = Env(tmp_path, cap=0.5)
    assert env.backfill() == EXIT_BUDGET
    assert env.billed() == Counter() and env.fb.spend == []
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"
    st = env.store.load_backfill()
    assert st["findall_id"] is None and not st["finished_at"]
    assert any("stopped on the budget" in m for m in env.logs)
    # Nothing reached Parallel, so the next invocation's own settings apply.
    env.fb.cap = 5.0
    assert env.backfill(days=14) == EXIT_OK
    assert next(r for k, r in env.p.requests if k == "findall.create") == create_request("2026-09-23", END, "base", 20)
    assert not any("resuming" in m for m in env.logs)


def test_402_on_the_enrich_then_resume_never_creates_twice(tmp_path):
    env = Env(tmp_path, cap=0.9)  # the $0.85 create fits; the $0.07 enrichment does not
    assert env.backfill() == EXIT_BUDGET
    assert env.billed() == Counter({"findall.create": 1})
    assert ("backend", "refused", ENRICH_STEP) in env.journal
    st = env.store.load_backfill()
    assert st["findall_id"] == "findall_1" and st["enrich_requested"] is False and st["matches"] == 7

    env.fb.cap = 5.0
    assert env.backfill(days=14, limit=50) == EXIT_OK  # resumes the saved run and its settings
    assert env.billed() == Counter({"findall.create": 1, "findall.enrich": 1, "search": 1})
    assert env.steps().count(CREATE_STEP) == 1 and env.steps().count(ENRICH_STEP) == 1
    assert any("resuming findall_1" in m for m in env.logs)
    assert len(env.store.load_queue()) == 3


def test_deadline_saves_the_findall_id_and_the_rerun_resumes_polling(tmp_path):
    env = Env(tmp_path)
    env.p.findall_active_polls = -1  # discovery never finishes in this invocation
    assert env.backfill(deadline_s=100) == EXIT_INCOMPLETE
    assert next(iter(env.fb.runs.values()))["status"] == "stopped"
    assert env.store.load_backfill()["findall_id"] == "findall_1" and env.store.load_queue() == []

    env.p.findall_active_polls = None
    assert env.backfill() == EXIT_OK
    assert env.billed()["findall.create"] == 1 and env.steps().count(CREATE_STEP) == 1
    assert len(env.store.load_queue()) == 3


def test_enrichment_still_running_at_the_deadline_resumes_without_a_second_enrich(tmp_path):
    env = Env(tmp_path)
    env.p.findall_enrich_active_polls = -1
    assert env.backfill(deadline_s=100) == EXIT_INCOMPLETE
    assert env.store.load_backfill()["enrich_requested"] is True
    env.p.findall_enrich_active_polls = None
    assert env.backfill() == EXIT_OK
    assert env.billed() == Counter({"findall.create": 1, "findall.enrich": 1, "search": 1})


def test_ambiguous_create_failure_is_reserved_again_on_the_retry(tmp_path):
    env = Env(tmp_path)
    real_create = env.p.beta.findall.create
    calls = {"n": 0}

    def flaky(**req):
        if calls["n"] == 0:
            calls["n"] += 1
            raise ConnectionError("read timeout")  # may have reached Parallel
        return real_create(**req)

    env.p.beta.findall.create = flaky
    with pytest.raises(ConnectionError):
        env.backfill()
    assert next(iter(env.fb.runs.values()))["status"] == "error"
    assert env.backfill() == EXIT_OK
    assert env.steps()[:2] == [CREATE_STEP, f"{CREATE_STEP}#retry1"]


def test_finished_backfill_is_not_paid_for_again_without_new(tmp_path):
    env = Env(tmp_path)
    assert env.backfill() == EXIT_OK
    runs = len(env.fb.runs)
    assert env.backfill() == EXIT_OK
    assert len(env.fb.runs) == runs and env.billed()["findall.create"] == 1
    assert any("pass --new" in m for m in env.logs)
    assert env.backfill(new=True) == EXIT_OK
    assert env.billed()["findall.create"] == 2 and env.store.load_backfill()["findall_id"] == "findall_2"


def test_no_matches_finishes_without_an_enrichment(tmp_path):
    env = Env(tmp_path)
    env.p.findall_candidates = [company_match("Nope", "https://nope.ai", matched=False)]
    assert env.backfill() == EXIT_OK
    assert env.billed() == Counter({"findall.create": 1})
    assert env.store.load_backfill()["finished_at"] and env.store.load_queue() == []


def test_exclude_skips_domains(tmp_path):
    env = Env(tmp_path)
    assert env.backfill(exclude=frozenset({"navra.io"})) == EXIT_OK
    assert [q["domain"] for q in env.store.load_queue()] == ["raindrop.ai", "mysterylabs.dev"]


def test_settings_over_the_run_budget_are_refused_before_any_call(tmp_path):
    env = Env(tmp_path)
    assert env.backfill(generator="core", limit=20) == EXIT_ERROR  # $2 + 20 x $0.15 + ... > $5
    assert env.backfill(generator="preview", limit=20) == EXIT_ERROR  # preview evaluates 5-10
    assert env.fb.requests == [] and env.journal == []


def test_dry_run_prints_the_requests_and_calls_nothing(tmp_path):
    env = Env(tmp_path)
    assert env.backfill(dry_run=True) == EXIT_OK
    assert env.fb.requests == [] and env.journal == [] and env.store.load_backfill() is None
    out = "\n".join(env.logs)
    assert '"entity_type": "companies"' in out and '"generator": "base"' in out and '"match_limit": 20' in out
    assert "between 2026-09-07 and 2026-10-07 (inclusive)" in out
    assert '"processor": "base"' in out and "$0.850" in out and "at most $1.15" in out
    assert "domain lookups up to 20 x $0.005" in out


def test_dry_run_of_a_backfill_in_progress_says_it_would_resume(tmp_path):
    env = Env(tmp_path)
    env.p.findall_active_polls = -1
    assert env.backfill(deadline_s=100) == EXIT_INCOMPLETE
    before = len(env.fb.requests)
    env.logs.clear()
    assert env.backfill(dry_run=True) == EXIT_OK
    assert len(env.fb.requests) == before
    assert any("would resume findall_1" in m for m in env.logs)
    assert not any("findall.create(**request)" in m for m in env.logs)


def test_backfilled_event_reaches_the_posted_card(tmp_path):
    env = Env(tmp_path)
    assert env.backfill() == EXIT_OK
    # `run` researches the queue; its own FindAll (people) sees leader candidates.
    env.p.findall_candidates = [candidate("Sam Rivera", "https://linkedin.com/in/example-sam-rivera")]
    env.p.pedigree_by_name = {"Sam Rivera": ({"current_title": "CEO"}, {})}
    env.p.brief_content = {"one_liner": "x", "ats": {"provider": "none", "board_token": None, "board_url": None}}
    env.p.team_content = {"profiles_found": 3.0}
    assert run(RunOptions(max_companies=1), env.deps()) == EXIT_OK
    event = env.fb.cards["raindrop.ai"]["payload"]["event"]
    assert event == {"type": "funding", "headline": "Raindrop raises $15M Series A",
                     "source_url": "https://techcrunch.com/2026/09/17/raindrop", "announced_at": "2026-09-17",
                     "round": "Series A", "amount_usd": "$15M", "investors": "CRV, Lightspeed",
                     "origin": "findall_backfill"}
    assert [q["domain"] for q in env.store.load_queue()] == ["mysterylabs.dev", "navra.io"]


# ---- CLI ------------------------------------------------------------------------------------
def test_parser_defaults_and_bounds():
    a = radar.build_parser().parse_args(["backfill"])
    assert (a.days, a.limit, a.generator, a.deadline_s, a.dry_run, a.new) == (30, 20, "base", 540.0, False, False)
    for argv in (["backfill", "--limit", "4"], ["backfill", "--limit", "101"], ["backfill", "--days", "0"],
                 ["backfill", "--generator", "pro"]):
        with pytest.raises(SystemExit):
            radar.build_parser().parse_args(argv)


def test_dry_run_through_main_needs_no_parallel_key_and_calls_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:9")  # nothing listens: any request would fail
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("LAUNCH_RADAR_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(radar.signal, "signal", lambda *a: None)  # keep pytest's SIGTERM handler
    assert radar.main(["backfill", "--dry-run", "--days", "14", "--limit", "10"]) == 0
    assert not (tmp_path / "backfill.json").exists()


def test_billed_backfill_through_main_requires_the_parallel_key(monkeypatch, capsys):
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    assert radar.main(["backfill"]) == 1
    assert "PARALLEL_API_KEY is not set" in capsys.readouterr().err
