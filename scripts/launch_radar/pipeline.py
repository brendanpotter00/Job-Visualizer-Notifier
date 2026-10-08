"""One loop invocation (CONTRACT §6.3) and the per-company research pipeline.

Spend rule: every billed Parallel call is preceded by a backend reservation
(``POST /runs/{uuid}/reserve``). A 402 stops new work; nothing is ever called
"on credit". A saved Parallel id is never created again and a saved
reservation is never made again. If a create call fails in a way that may
still have reached Parallel (a timeout or a dropped connection: the id was
never saved), the retry is reserved AGAIN under a ``#retryN`` step, so the
ledger over-counts a possible double charge instead of missing it. The pedigree
group's ``add_runs`` follows the same rule, after first asking the group whether
the earlier request landed (``CompanyJob.add_pedigree_runs``).
"""

from __future__ import annotations

import re
import socket
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx

from . import monitors as mon
from .ats import check_board
from .backend_client import BackendClient, BudgetExceeded, DomainSeen
from .card import build_payload, text
from .domains import is_big_tech, is_hostname, normalize_domain
from .leaders import (
    BRIEF_LEADERS_ISSUE,
    BriefLeader,
    Deadline,
    DeadlineReached,
    RetryLater,
    add_pedigree_runs,
    brief_founders,
    brief_leaders,
    collect_pedigree,
    create_pedigree_group,
    findall_request,
    pedigree_inputs,
    pedigree_run_count,
    poll_findall,
    poll_group,
    select_leaders,
)
from .parallel_client import status_code_of
from .research import (
    TaskFailed,
    brief_request,
    create_task,
    task_output,
    team_request,
    wait_task,
)
from .resolve import MAX_LOOKUPS_PER_RUN, SEARCH_PRICE, resolve_missing_domains
from .schemas import FINDALL_PRICE, TASK_PRICE, ceil_cost
from .state import StateStore, iso, parse_iso, utc_now

Log = Callable[[str], None]

EXIT_OK, EXIT_ERROR, EXIT_BUDGET, EXIT_INCOMPLETE = 0, 1, 2, 3
CANCEL_FLOOR_USD = 0.10
ADMIN_RUN_BUDGET_USD = 0.10
STALE_AFTER = timedelta(days=3)  # a queued Monitor event with no progress for this long is dropped
# The queue slot of the one-off ``backfill`` sweep's events. They are never dropped as stale: the
# sweep is a deliberate, already-paid search of the past month, drained a few companies per run,
# after any queued Monitor events (which do go stale).
BACKFILL_SLOT = "backfill"
MAX_WORKERS = 3
MIN_START_S = 60.0  # do not start a new company with less time than this left
MAX_RETRIES = 6  # invocations that hit a transient error before the card posts with the gap noted
ATS_TIMEOUT_S = 20.0
POST_RESERVE_S = 35.0  # time post_card needs (its client timeout is 30s)
PEDIGREE_STEP = "task_group(pedigree)"  # the ledger step that covers the group and its runs
PEDIGREE_RUNS_KEY = "pedigree_runs"  # the ``attempts`` key for ``add_runs``


@dataclass
class RunOptions:
    max_companies: int = 3
    budget: float = 1.0
    exclude: frozenset[str] = frozenset()
    deadline_s: float = 540.0
    dry_run: bool = False


@dataclass
class Deps:
    backend: BackendClient
    make_client: Callable[[], Any]
    store: StateStore
    log: Log
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = utc_now
    clock: Callable[[], float] = time.monotonic
    wall: Callable[[], float] = time.time
    ats_transport: httpx.BaseTransport | None = None
    host: str = field(default_factory=socket.gethostname)


@dataclass
class Outcome:
    domain: str
    status: str  # posted | seen | budget | deadline | retry | not_started | error
    detail: str = ""
    card_id: int | None = None


# ---- dedupe ----------------------------------------------------------------------
def _rank(ev: dict[str, Any]) -> tuple[int, str]:
    """POC ``_rank``: Series A first, then seed, then later rounds, then launches."""
    rnd = (ev.get("round") or "").lower()
    score = 0
    if ev.get("event_type") == "funding":
        score = 60
        if "series a" in rnd:
            score = 100
        elif "seed" in rnd:
            score = 80
        elif re.search(r"series [b-z]", rnd):
            score = 70
    elif ev.get("event_type") == "launch":
        score = 50
    return score, ev.get("announced_at") or ""


def dedupe(
    candidates: list[dict[str, Any]],
    backend: BackendClient,
    queued: set[str],
    exclude: frozenset[str],
    now: datetime,
    log: Log,
    reasons: Counter[str] | None = None,
) -> list[dict[str, Any]]:
    """Queue items for the candidates that survive every filter, best first. No spend happens here.

    ``reasons``, when given, counts every skip by its reason (for a summary line).
    """
    skipped: Counter[str] = reasons if reasons is not None else Counter()
    local: list[tuple[str, dict[str, Any]]] = []
    taken = set(queued)
    for c in candidates:
        name = text(c.get("company_name"), 80) or "?"
        dom = normalize_domain(c.get("company_domain"))
        reason = None
        if not dom:
            reason = "no domain"
        elif not is_hostname(dom):
            reason = "not a hostname"
        elif is_big_tech(dom):
            reason = "big tech"
        elif dom in exclude:
            reason = "excluded"
        elif dom in taken:
            reason = "already queued"
        if reason:
            log(f"skip {dom or name!r}: {reason}")
            skipped[reason] += 1
            continue
        assert dom is not None
        taken.add(dom)
        local.append((dom, c))
    if not local:
        return []
    seen = backend.seen([d for d, _ in local], [c["company_name"] for _, c in local if c.get("company_name")])
    tracked_names = {k.lower(): v for k, v in seen["names"].items()}
    items: list[dict[str, Any]] = []
    for dom, c in sorted(local, key=lambda dc: _rank(dc[1]), reverse=True):
        hit = seen["domains"].get(dom)
        if hit:
            log(f"skip {dom}: card {hit.get('card_id')} exists ({hit.get('status')})")
            skipped["card exists"] += 1
            continue
        tracked = tracked_names.get((c.get("company_name") or "").lower())
        if tracked:
            log(f"skip {dom}: already tracked as {tracked}")
            skipped["already tracked"] += 1
            continue
        items.append({"domain": dom, "company": text(c.get("company_name"), 200) or dom, "event": c,
                      "slot": c.get("slot"), "queued_at": iso(now)})
    return items


# ---- per-company research ---------------------------------------------------------
class CompanyJob:
    def __init__(self, item: dict[str, Any], run_uuid: str, client: Any, deps: Deps, deadline: Deadline,
                 stop: threading.Event) -> None:
        self.item = item
        self.domain: str = item["domain"]
        self.company: str = item["company"]
        self.run_uuid = run_uuid
        self.client = client
        self.deps = deps
        self.deadline = deadline
        self.stop = stop
        self.st: dict[str, Any] = {}

    def save(self) -> None:
        self.deps.store.save_company(self.domain, self.st)

    def load(self) -> dict[str, Any] | None:
        return self.deps.store.load_company(self.domain)

    def new_state(self) -> dict[str, Any]:
        return {"domain": self.domain, "company": self.company, "reserved": {}, "ids": {}, "t0": {},
                "issues": [], "started_at": iso(self.deps.now())}

    def open_state(self) -> Outcome | None:
        """Load the saved state, or start a new one; ``not_started`` when nothing is saved and
        the run is stopping (a 402) or too close to its deadline to start paid work."""
        loaded = self.load()
        if loaded is None:
            if self.stop.is_set():
                return Outcome(self.domain, "not_started", "budget stop")
            if self.deadline.remaining() < MIN_START_S:
                return Outcome(self.domain, "not_started", "deadline")
            loaded = self.new_state()
        self.st = loaded
        return None

    def reserve(self, step: str, est: float) -> None:
        """Reserve once per step for this company; the reservation survives a resume."""
        if step in self.st["reserved"]:
            return
        self.deps.backend.reserve(self.run_uuid, step, est, domain=self.domain)
        self.st["reserved"][step] = est
        self.save()

    def billed(self, step: str, est: float, id_key: str, create: Callable[[], str]) -> str:
        existing = self.st["ids"].get(id_key)
        if existing:
            return str(existing)
        attempts = self.st.setdefault("attempts", {})
        prior = int(attempts.get(id_key, 0))
        if prior:
            # An earlier create may have reached Parallel without its id being saved
            # (timeout, dropped connection): that attempt may have billed. Reserve again.
            step = f"{step}#retry{prior}"
            self.deps.log(f"{self.domain}: re-creating {step} after an ambiguous failure; "
                          f"the previous attempt may have billed")
        self.reserve(step, est)
        attempts[id_key] = prior + 1
        self.st["t0"][id_key] = self.deps.wall()
        self.save()
        try:
            new_id = create()
        except Exception as e:
            code = status_code_of(e)
            if code is not None and 400 <= code < 500 and code not in (408, 429):
                # Parallel answered and refused the request: nothing was created or billed.
                attempts[id_key] = prior
                self.save()
            raise
        self.st["ids"][id_key] = new_id
        self.save()
        self.deps.log(f"{self.domain}: {step} -> {new_id}")
        return new_id

    def mark_done(self, key: str) -> float:
        done = self.st.setdefault("done", {})
        if key not in done:
            done[key] = self.deps.wall()
            self.save()
        return round(done[key] - self.st["t0"].get(key, done[key]), 1)

    def issue(self, msg: str) -> None:
        if msg not in self.st["issues"]:
            self.st["issues"].append(msg)

    def run(self) -> Outcome:
        not_started = self.open_state()
        if not_started is not None:
            return not_started
        try:
            return self._research()
        except BudgetExceeded as e:
            self.stop.set()
            return Outcome(self.domain, "budget", str(e))
        except DeadlineReached as e:
            return Outcome(self.domain, "deadline", f"waiting on {e}")
        except RetryLater as e:
            self.st["retries"] = int(self.st.get("retries", 0)) + 1
            self.save()
            return Outcome(self.domain, "retry", f"transient error, will resume "
                                                 f"({self.st['retries']}/{MAX_RETRIES}): {e}")

    @property
    def final_attempt(self) -> bool:
        """After MAX_RETRIES transient failures, post the card with the gap recorded as an issue."""
        return int(self.st.get("retries", 0)) >= MAX_RETRIES

    def _research(self) -> Outcome:
        c, d = self.client, self.deps
        event = self.item.get("event") or {}
        fid = self.billed("findall.create", ceil_cost(FINDALL_PRICE["preview"][0]), "findall_id",
                          lambda: str(c.beta.findall.create(**findall_request(self.company, self.domain)).findall_id))
        brief_id = self.billed("task_run.create(brief)", ceil_cost(TASK_PRICE["core"]), "brief_run_id",
                               lambda: create_task(c, brief_request(self.company, self.domain, event.get("headline"))))
        team_id = self.billed("task_run.create(team)", ceil_cost(TASK_PRICE["pro"]), "team_run_id",
                              lambda: create_task(c, team_request(self.company, self.domain)))
        timings: dict[str, float] = {}

        # Leaders: FindAll preview, then is_person.
        fa_run = poll_findall(c, fid, self.deadline, d.sleep)
        timings["findall_s"] = self.mark_done("findall_id")
        if getattr(fa_run.status, "status", None) != "completed":
            self.issue(f"findall ended {fa_run.status.status} ({getattr(fa_run.status, 'termination_reason', None)})")
        result = c.beta.findall.result(fid)
        leaders, dropped = self._leaders(result)
        brief_out: tuple[dict[str, Any] | None, list[Any]] | None = None
        if not self.st["leader_ids"]:
            # FindAll confirmed no person: fall back to the brief's founders. The brief was
            # created with FindAll at t=0, so the pedigree step waits for it here.
            brief_out = self._wait("brief_run_id", brief_id, "brief", timings)
            leaders = list(self.leaders_from_brief(brief_out[0]))
            if leaders:
                self.issue(BRIEF_LEADERS_ISSUE + (f"; {dropped} company page(s) dropped" if dropped else ""))

        # Pedigree: one Task Group, one base run per leader. A None entry is a leader
        # missing on resume; it keeps its index so row_id still joins the right person.
        pedigree = self.run_pedigree(leaders, timings)
        if not leaders:
            self.issue("no leaders confirmed" + (f"; {dropped} company page(s) dropped" if dropped else ""))

        # Brief and team tally (created at t=0, usually finished by now).
        brief, brief_basis = brief_out or self._wait("brief_run_id", brief_id, "brief", timings)
        team, _ = self._wait("team_run_id", team_id, "team tally", timings, key="team_s")

        raw_ats = (brief or {}).get("ats")
        ats_in: dict[str, Any] = raw_ats if isinstance(raw_ats, dict) else {}
        self.deadline.check("ats check")
        board = check_board(ats_in.get("provider"), ats_in.get("board_token"), (brief or {}).get("careers_url"),
                            ats_in.get("board_url"), transport=d.ats_transport,
                            timeout_s=max(1.0, min(ATS_TIMEOUT_S, self.deadline.remaining() - POST_RESERVE_S)))
        if board.transient_failure and not self.final_attempt:
            raise RetryLater("; ".join(p.note() for p in board.problems if p.transient))
        if not board.ats["verified"] or not board.ats["job_count"]:
            for prob in board.problems:
                self.issue(prob.note())
        ats = board.ats

        if self.deadline.remaining() < POST_RESERVE_S:
            raise DeadlineReached("posting the card")
        payload = build_payload(
            company=self.company, domain=self.domain, monitor_event=event or None, brief=brief,
            brief_basis=brief_basis,
            leaders=[(cd, pedigree.get(i)) for i, cd in enumerate(leaders) if cd is not None],
            leaders_dropped=dropped, team=team, ats=ats,
            run_ids={"findall_id": fid, "brief_run_id": brief_id, "team_run_id": team_id,
                     "pedigree_group_id": self.st["ids"].get("pedigree_group_id")},
            cost_usd=sum(float(v) for v in self.st["reserved"].values()), timings=timings,
            issues=list(self.st["issues"]), generated_at=iso(d.now()),
        )
        try:
            posted = d.backend.post_card(self.run_uuid, payload)
            out = Outcome(self.domain, "posted",
                          f"talent {payload['scores']['talent']} vc {payload['scores']['vc']} "
                          f"${payload['cost_usd']:.3f}" + (" already tracked" if posted.get("tracked_company_id") else ""),
                          card_id=posted.get("id"))
        except DomainSeen:
            out = Outcome(self.domain, "seen", "card already exists (409)")
        d.store.remove_from_queue(self.domain)
        d.store.delete_company(self.domain)
        return out

    def leaders_from_brief(self, brief: dict[str, Any] | None) -> list[BriefLeader]:
        """The brief's cleaned ``founders`` as leaders. Saved on first use, so a resume
        runs the pedigree on exactly the same people in the same order (row_id = index)."""
        saved = self.st.get("brief_leaders")
        if saved is None:
            saved = brief_founders(brief)
            self.st["brief_leaders"] = saved
            self.save()
        return brief_leaders(saved)

    def run_pedigree(self, leaders: list[Any], timings: dict[str, float]) -> dict[int, dict[str, Any]]:
        """Reserve, create, fill and collect the pedigree Task Group (one base run per present
        leader). Each step runs once: a saved group id and ``pedigree_runs_added`` survive a
        resume, and an ambiguous ``add_runs`` failure is checked against the group before any
        re-add (``add_pedigree_runs``)."""
        c, d = self.client, self.deps
        present = {i for i, cd in enumerate(leaders) if cd is not None}
        if not present:
            return {}
        est = ceil_cost(len(present) * TASK_PRICE["base"])
        gid = self.billed(PEDIGREE_STEP, est, "pedigree_group_id", lambda: create_pedigree_group(c, self.domain))
        if not self.st.get("pedigree_runs_added"):
            self.add_pedigree_runs(gid, leaders, est)
        poll_group(c, gid, self.deadline, d.sleep)
        timings["pedigree_s"] = self.mark_done("pedigree_group_id")
        pedigree, ped_issues = collect_pedigree(c, gid, len(leaders), expected=present)
        for msg in ped_issues:
            self.issue(msg)
        return pedigree

    def add_pedigree_runs(self, gid: str, leaders: list[Any], est: float) -> None:
        """``add_runs`` on the group, at most once per reservation.

        Adding the runs is what bills, and Parallel adds them again on a second call. So an
        attempt is recorded BEFORE the call, like ``billed``. When an earlier attempt failed
        in a way that may still have reached Parallel (a timeout, a dropped connection), the
        group is asked first (a free ``retrieve``): if it holds runs, that request landed and
        they are marked added; if it holds none, the runs are added again under a fresh
        ``task_group(pedigree)#retryN`` reservation, so the ledger over-counts a possible
        double charge (the group may not show an accepted request yet) instead of missing it.
        A refusal (a 4xx other than 408/429: nothing was added) does not count as an attempt.
        """
        c, d = self.client, self.deps
        attempts = self.st.setdefault("attempts", {})
        prior = int(attempts.get(PEDIGREE_RUNS_KEY, 0))
        if prior:
            held = pedigree_run_count(c, gid)
            if held:
                d.log(f"{self.domain}: pedigree group {gid} already holds {held} run(s) from an earlier "
                      f"attempt; not adding them again")
                self.st["pedigree_runs_added"] = True
                self.save()
                return
            step = f"{PEDIGREE_STEP}#retry{prior}"
            d.log(f"{self.domain}: re-adding the pedigree runs under {step}; group {gid} holds none")
            self.reserve(step, est)
        attempts[PEDIGREE_RUNS_KEY] = prior + 1
        self.save()
        try:
            add_pedigree_runs(c, gid, pedigree_inputs(leaders, self.company, self.domain))
        except Exception as e:
            code = status_code_of(e)
            if code is not None and 400 <= code < 500 and code not in (408, 429):
                attempts[PEDIGREE_RUNS_KEY] = prior  # Parallel refused: nothing was added or billed
                self.save()
            raise
        self.st["pedigree_runs_added"] = True
        self.save()

    def _leaders(self, result: Any) -> tuple[list[Any], int]:
        kept, dropped = select_leaders(result)
        saved = self.st.get("leader_ids")
        if saved is None:
            self.st["leader_ids"] = [getattr(cd, "candidate_id", None) for cd in kept]
            self.st["leaders_dropped"] = dropped
            self.save()
            return kept, dropped
        # Resume: keep the saved order (row_id = index). A leader missing from the new
        # result stays as a None placeholder so the indexes after it do not shift.
        by_id = {getattr(cd, "candidate_id", None): cd for cd in result.candidates or []}
        out: list[Any] = []
        for i, cid in enumerate(saved):
            cd = by_id.get(cid)
            if cd is None:
                self.issue(f"leader {i + 1} ({cid}) missing from the FindAll result on resume; skipped")
            out.append(cd)
        return out, int(self.st.get("leaders_dropped", dropped))

    def _wait(self, id_key: str, run_id: str, label: str, timings: dict[str, float],
              key: str | None = None) -> tuple[dict[str, Any] | None, list[Any]]:
        try:
            res = wait_task(self.client, run_id, self.deadline)
        except TaskFailed as e:
            self.issue(f"{label} failed: {e}")
            return None, []
        except RetryLater as e:
            if not self.final_attempt:
                raise
            self.issue(f"{label} not collected after {MAX_RETRIES} attempts: {e}")
            return None, []
        timings[key or f"{label}_s"] = self.mark_done(id_key)
        content, basis = task_output(res)
        if content is None:
            self.issue(f"{label} returned no JSON")
        return content, basis


# ---- the run ------------------------------------------------------------------------
@dataclass
class RunCounters:
    events_read: int = 0
    cards_posted: int = 0


def _read_all_events(
    client: Any, monitors: list[dict[str, Any]], log: Log
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Events, the newest id per slot, and the slots whose read was truncated."""
    events: list[dict[str, Any]] = []
    newest: dict[str, str] = {}
    truncated: list[str] = []
    for m in mon.active(monitors):
        got, top, cut = mon.read_events(client, m, log)
        log(f"monitor {m['slot']}: {len(got)} new event(s)")
        events += got
        if cut:
            truncated.append(m["slot"])
        if top and top != m.get("last_event_id"):
            newest[m["slot"]] = top
    return events, newest, truncated


def dry_run(opts: RunOptions, deps: Deps) -> int:
    """Free: reads events and ``GET /seen`` only. No billed call, no backend write, no local write."""
    monitors = mon.active(deps.backend.list_monitors())
    if not monitors:
        deps.log("no active monitors (run monitors-ensure)")
    client = deps.make_client() if monitors else None
    events, _, _ = _read_all_events(client, monitors, deps.log) if client is not None else ([], {}, [])
    queue = deps.store.load_queue()
    items = dedupe(events, deps.backend, {q["domain"] for q in queue}, opts.exclude, deps.now(), deps.log)
    for q in queue:
        deps.log(f"queued: {q['domain']} ({q['company']})" + (" [in progress]" if deps.store.has_company(q["domain"]) else ""))
    for it in items:
        ev = it["event"]
        deps.log(f"would research: {it['domain']} ({it['company']}) {ev.get('event_type')} "
                 f"{ev.get('round') or ''} {ev.get('amount_usd') or ''}".rstrip())
    no_domain = sum(1 for ev in events if not normalize_domain(ev.get("company_domain")))
    if no_domain:
        deps.log(f"dry run: {no_domain} event(s) have no domain; a real run looks them up with the Search API "
                 f"(${SEARCH_PRICE:.3f} each, at most {MAX_LOOKUPS_PER_RUN} per run)")
    deps.log(f"dry run: {len(events)} event(s), {len(items)} new candidate(s), {len(queue)} queued; nothing spent")
    return EXIT_OK


def run(opts: RunOptions, deps: Deps) -> int:
    if opts.dry_run:
        return dry_run(opts, deps)
    run_uuid = uuid.uuid4().hex
    started = deps.backend.start_run(run_uuid, deps.host, opts.budget)
    deps.log(f"run {started['run_id']} · spend before ${started['total_spend_usd']:.2f} of ${started['cap_usd']:.2f}"
             f" · budget ${opts.budget:.2f}")
    counters = RunCounters()
    try:
        code, status, notes = _run_body(opts, deps, run_uuid, started, counters)
    except BaseException as e:  # incl. SystemExit from the SIGTERM handler: the run row must not stay "running"
        deps.log(f"run {run_uuid} failed: {type(e).__name__}: {e}")
        try:
            deps.backend.finish_run(run_uuid, "error", counters.events_read, counters.cards_posted,
                                    f"{type(e).__name__}: {e}"[:500])
        except Exception as fin_err:
            deps.log(f"could not finish run {run_uuid}: {type(fin_err).__name__}: {fin_err}")
        raise
    fin = deps.backend.finish_run(run_uuid, status, counters.events_read, counters.cards_posted,
                                  notes[:500])  # the backend's notes limit
    deps.log(f"{counters.cards_posted} card(s) · run ${fin['run_spend_usd']:.2f} · total "
             f"${fin['total_spend_usd']:.2f} of ${started['cap_usd']:.2f} · {status}")
    return code


def _run_body(opts: RunOptions, deps: Deps, run_uuid: str, started: dict[str, Any],
              counters: RunCounters) -> tuple[int, str, str]:
    log, store = deps.log, deps.store
    deadline = Deadline(opts.deadline_s, deps.clock)
    monitors = mon.active(started.get("monitors") or [])

    # 2. Accrue scheduled Monitor executions; the cap stops the Monitors.
    over_cap, last = mon.accrue(deps.backend, run_uuid, monitors, deps.now(), log)
    total = float(last["total_spend_usd"]) if last else float(started["total_spend_usd"])
    remaining = float(started["cap_usd"]) - total
    client: Any = None
    if over_cap or remaining < CANCEL_FLOOR_USD:
        log(f"spend cap reached (${total:.2f} of ${started['cap_usd']:.2f}): cancelling monitors")
        # Always ask Parallel too: cancel_all also finds tagged orphans the backend has no
        # active row for. Cancelling is free.
        cancelled = mon.cancel_all(deps.make_client(), deps.backend, log)
        return EXIT_BUDGET, "stopped", f"spend cap reached; cancelled {len(cancelled)} monitor(s)"

    # 3-4. Read new events, dedupe, persist the survivors, then move the cursors.
    extra_notes: list[str] = []
    if monitors:
        client = deps.make_client()
    else:
        log("no active monitors (run monitors-ensure); only queued companies can be researched")
        extra_notes.append("no active monitors")
    events, newest, truncated = _read_all_events(client, monitors, log) if client is not None else ([], {}, [])
    if truncated:
        extra_notes.append(f"events truncated ({', '.join(truncated)})")
    counters.events_read = len(events)
    if client is not None and events:
        # Most news events carry no website; dedupe needs one. One Search API call each ($0.005),
        # reserved first. On the cap, stop before the cursors move: next run reads them again.
        try:
            resolve_missing_domains(events, client, lambda step, est: deps.backend.reserve(run_uuid, step, est), log)
        except BudgetExceeded as e:
            log(f"domain lookup stopped on the budget: {e}")
            return EXIT_BUDGET, "stopped", f"budget reached during domain lookup: {e}"
    queue = store.load_queue()
    items = dedupe(events, deps.backend, {q["domain"] for q in queue}, opts.exclude, deps.now(), log)
    store.append_queue(items)
    for slot, event_id in newest.items():
        deps.backend.patch_monitor(slot, last_event_id=event_id)

    # 5. Research: resumed companies always continue; up to --max-companies new ones start.
    now = deps.now()
    queue = store.load_queue()
    resumed, fresh = [], []
    dropped = 0
    for q in queue:
        if store.has_company(q["domain"]):
            resumed.append(q)
        elif q.get("slot") != BACKFILL_SLOT and now - parse_iso(q["queued_at"]) > STALE_AFTER:
            log(f"drop {q['domain']}: queued {q['queued_at']} with no progress for 3 days")
            store.remove_from_queue(q["domain"])
            dropped += 1
        elif q["domain"] not in opts.exclude:
            fresh.append(q)
    if dropped:
        extra_notes.append(f"dropped {dropped} stale")
    # Monitor events start before backfill items. A Monitor event is dropped once it has
    # waited STALE_AFTER; a backfill item never is, so a long backfill queue ahead of it
    # would otherwise hold every new event back until it went stale. Stable sort: each
    # group keeps its queue (FIFO) order.
    fresh.sort(key=lambda q: q.get("slot") == BACKFILL_SLOT)
    work = resumed + fresh[: max(0, opts.max_companies)]
    if work and client is None:
        client = deps.make_client()
    stop = threading.Event()
    outcomes: list[Outcome] = []
    if work:
        # Not a `with` block: on SIGTERM (SystemExit here) the run must be finished at once,
        # not after every worker's long-poll returns. Workers see the aborted deadline.
        pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        try:
            futures = [(q["domain"], pool.submit(CompanyJob(q, run_uuid, client, deps, deadline, stop).run))
                       for q in work]
            for domain, fut in futures:
                try:
                    outcomes.append(fut.result())
                except Exception as e:  # recorded and reported below; the company keeps its state
                    outcomes.append(Outcome(domain, "error", f"{type(e).__name__}: {e}"[:300]))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    for o in outcomes:
        log(f"{o.status:<11} {o.domain}" + (f" card {o.card_id}" if o.card_id else "") + (f" — {o.detail}" if o.detail else ""))
    counters.cards_posted = sum(1 for o in outcomes if o.status == "posted")
    statuses = {o.status for o in outcomes}
    left = len(store.load_queue())
    notes = ", ".join(f"{s} {sum(1 for o in outcomes if o.status == s)}" for s in sorted(statuses)) or "no work"
    notes += f"; {left} queued"
    if extra_notes:
        notes += "; " + "; ".join(extra_notes)
    if "error" in statuses:
        return EXIT_ERROR, "error", notes
    if "budget" in statuses or stop.is_set():
        return EXIT_BUDGET, "stopped", notes
    if ("deadline" in statuses or "retry" in statuses
            or any(o.status == "not_started" and o.detail == "deadline" for o in outcomes)):
        return EXIT_INCOMPLETE, "stopped", notes
    idle = not monitors
    return EXIT_OK, ("ok" if left == 0 and not idle else "stopped"), notes


# ---- admin subcommands (each opens and finishes its own backend run) ---------------------
def admin_run(deps: Deps, label: str, body: Callable[[str], str], *, budget: float = ADMIN_RUN_BUDGET_USD,
              counters: RunCounters | None = None) -> int:
    """Open a backend run, call ``body(run_uuid)`` and finish the run with its notes.

    A 402 finishes it ``stopped`` (exit 2); a deadline (``DeadlineReached``, state saved by
    the body) finishes it ``stopped`` (exit 3); anything else, SIGTERM's SystemExit
    included, finishes it ``error`` and re-raises, so the run row never stays "running".
    ``counters`` lets the body report ``events_read`` / ``cards_posted``.
    """
    run_uuid = uuid.uuid4().hex
    c = counters if counters is not None else RunCounters()
    started = deps.backend.start_run(run_uuid, deps.host, budget)
    deps.log(f"{label}: run {started.get('run_id')} · spend before ${float(started.get('total_spend_usd', 0)):.2f} "
             f"of ${float(started.get('cap_usd', 0)):.2f} · budget ${budget:.2f}")

    def finish(status: str, notes: str) -> None:
        deps.backend.finish_run(run_uuid, status, c.events_read, c.cards_posted, notes[:500])

    try:
        notes = body(run_uuid)
    except BudgetExceeded as e:
        finish("stopped", f"{label}: {e}")
        deps.log(f"{label}: stopped on the budget: {e}")
        return EXIT_BUDGET
    except DeadlineReached as e:
        finish("stopped", f"{label}: deadline while waiting on {e}; re-run to resume")
        deps.log(f"{label}: deadline reached while waiting on {e}; state saved, re-run to resume")
        return EXIT_INCOMPLETE
    except BaseException as e:
        try:
            finish("error", f"{label}: {type(e).__name__}: {e}")
        except Exception as fin_err:
            deps.log(f"{label}: could not finish run {run_uuid}: {type(fin_err).__name__}: {fin_err}")
        raise
    finish("ok", notes)
    deps.log(f"{label}: {notes}")
    return EXIT_OK


def monitors_ensure(deps: Deps) -> int:
    def body(run_uuid: str) -> str:
        created = mon.ensure(deps.make_client(), deps.backend, run_uuid, deps.now(), deps.log)
        return f"created {', '.join(created)}" if created else "all monitors already active"

    return admin_run(deps, "monitors-ensure", body)


def monitors_cancel(deps: Deps) -> int:
    def body(run_uuid: str) -> str:
        cancelled = mon.cancel_all(deps.make_client(), deps.backend, deps.log)
        return f"cancelled and confirmed {len(cancelled)} monitor(s)"

    return admin_run(deps, "monitors-cancel", body)
