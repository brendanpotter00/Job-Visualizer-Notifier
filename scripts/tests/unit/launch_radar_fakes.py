"""Fakes for the Launch Radar loop tests: no network, no Parallel SDK, no backend.

- ``FakeParallel`` mimics the slice of the ``parallel-web`` client the loop uses
  (``monitor``, ``beta.findall``, ``task_run``, ``task_group``). Responses are
  ``SimpleNamespace`` objects with the SDK's attribute names.
- ``FakeBackend`` is an in-memory implementation of the backend's internal
  Launch Radar routes (CONTRACT §2.3), mounted as an ``httpx.MockTransport``,
  including the ledger semantics (402 on run budget / cap, accrued rows always
  inserted) and the 409 on a duplicate domain.

Both append to one shared ``journal`` so a test can assert the order of
reservations and billed calls.
"""

from __future__ import annotations

import json
from itertools import count
from types import SimpleNamespace as NS
from typing import Any, Callable
from urllib.parse import parse_qs

import httpx
from launch_radar.domains import normalize_domain

PREFIX = "/api/internal/launch-radar"


class FakeAPIStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


# ---- Parallel SDK object builders ---------------------------------------------------
def citation(url: str, title: str | None = None) -> NS:
    return NS(url=url, title=title, excerpts=None)


def basis(field: str, confidence: str | None = "high", urls: tuple[str, ...] = ()) -> NS:
    return NS(field=field, confidence=confidence, citations=[citation(u) for u in urls], reasoning="")


def candidate(name: str, url: str, *, matched: bool = True, cid: str | None = None,
              description: str | None = None, basis_list: list[NS] | None = None) -> NS:
    return NS(candidate_id=cid or f"cand_{name.replace(' ', '_').lower()}", name=name, url=url,
              description=description, match_status="matched" if matched else "unmatched",
              output={}, basis=basis_list or [])


def company_match(name: str, url: str, *, matched: bool = True, cid: str | None = None,
                  announcement_url: str | None = None) -> NS:
    """A backfill (``entity_type="companies"``) candidate with its match-condition outputs."""
    cd = candidate(name, url, matched=matched, cid=cid, description=f"{name} is a startup.")
    cd.output = {"early_stage_startup_check": {"value": "yes", "type": "match_condition", "is_matched": matched},
                 "recent_announcement_check": {"value": "announced in the window", "type": "match_condition",
                                               "is_matched": matched}}
    if announcement_url:
        cd.basis = [basis("recent_announcement_check", "high", (announcement_url,))]
    return cd


def stream_event(event_id: str, content: dict[str, Any] | str, event_date: str = "2026-10-06") -> NS:
    return NS(event_type="event_stream", event_id=event_id, event_group_id="mevtgrp_1", event_date=event_date,
              output=NS(type="json", content=content, basis=[]))


def monitor_content(name: str, domain: str | None, *, event_type: str = "funding", rnd: str | None = "Series A",
                    amount: str | None = "$35M", investors: str | None = "CRV, Lightspeed") -> dict[str, Any]:
    return {"company_name": name, "company_domain": domain, "event_type": event_type, "round": rnd,
            "amount_usd": amount, "investors": investors, "announced_at": "2026-09-17",
            "source_url": f"https://news.example.com/{name.lower().replace(' ', '-')}",
            "headline": f"{name} raises {amount}"}


# ---- FakeParallel ------------------------------------------------------------------------
class _Monitor:
    def __init__(self, p: "FakeParallel") -> None:
        self.p = p
        self.ids = count(1)
        self.status: dict[str, str] = {}
        self.pages: dict[str, list[NS]] = {}  # monitor_id -> pages (NS(events, next_cursor))
        self.stuck: set[str] = set()  # cancel does not take effect

    def create(self, **req: Any) -> NS:
        mid = f"monitor_{next(self.ids)}"
        self.p.journal.append(("parallel", "monitor.create", req["metadata"]["slot"]))
        self.p.requests.append(("monitor.create", req))
        self.status[mid] = "active"
        return NS(monitor_id=mid, status="active", frequency=req["frequency"], processor=req["processor"])

    def events(self, monitor_id: str, limit: int = 20, cursor: str | None = None) -> NS:
        self.p.journal.append(("parallel", "monitor.events", monitor_id))
        pages = self.pages.get(monitor_id, [NS(events=[], next_cursor=None)])
        idx = int(cursor) if cursor else 0
        return pages[idx]

    def cancel(self, monitor_id: str) -> NS:
        self.p.journal.append(("parallel", "monitor.cancel", monitor_id))
        if monitor_id not in self.stuck:
            self.status[monitor_id] = "cancelled"
        return NS(monitor_id=monitor_id, status=self.status.get(monitor_id, "cancelled"))

    def retrieve(self, monitor_id: str) -> NS:
        return NS(monitor_id=monitor_id, status=self.status.get(monitor_id, "active"))

    def list(self, limit: int = 100, cursor: str | None = None) -> NS:
        return NS(monitors=[NS(monitor_id=m, status=s, metadata={"app": "launch-radar"})
                            for m, s in self.status.items() if s == "active"], next_cursor=None)


class _FindAll:
    def __init__(self, p: "FakeParallel") -> None:
        self.p = p
        self.ids = count(1)
        self.polls: dict[str, int] = {}
        self.enrich_polls: dict[str, int] = {}  # fid -> retrieves since its enrich request

    def create(self, **req: Any) -> NS:
        fid = f"findall_{next(self.ids)}"
        meta = req.get("metadata") or {}
        self.p.journal.append(("parallel", "findall.create", meta.get("company") or meta.get("step")))
        self.p.requests.append(("findall.create", req))
        self.polls[fid] = 0
        return NS(findall_id=fid)

    def enrich(self, fid: str, *, output_schema: dict[str, Any], processor: str = "core") -> NS:
        self.p.journal.append(("parallel", "findall.enrich", fid))
        self.p.requests.append(("findall.enrich", {"findall_id": fid, "output_schema": output_schema,
                                                   "processor": processor}))
        self.enrich_polls[fid] = 0
        return NS(objective="o", entity_type="companies", match_conditions=[], enrichments=[])

    def _active(self, fid: str) -> bool:
        if fid in self.enrich_polls:  # an enrichment requeues the run
            self.enrich_polls[fid] += 1
            polls, n = self.enrich_polls[fid], self.p.findall_enrich_active_polls
        else:
            self.polls[fid] = self.polls.get(fid, 0) + 1
            polls, n = self.polls[fid], self.p.findall_active_polls
        return False if n is None else (True if n < 0 else polls <= n)

    def retrieve(self, fid: str) -> NS:
        active = self._active(fid)
        return NS(findall_id=fid, status=NS(status="running" if active else "completed", is_active=active,
                                             termination_reason=None if active else "low_match_rate"))

    def result(self, fid: str) -> NS:
        if fid not in self.enrich_polls:
            return NS(candidates=list(self.p.findall_candidates))
        # After the enrich request: each matched candidate gains its enrichment fields
        # (``findall_enrichment[candidate_id]``) as ``{"value": ..., "type": "enrichment"}``.
        out = []
        for cd in self.p.findall_candidates:
            fields = self.p.findall_enrichment.get(cd.candidate_id)
            if cd.match_status == "matched" and fields is not None:
                cd = NS(**{**vars(cd), "output": {**(cd.output or {}), **{
                    k: {"value": v, "type": "enrichment"} for k, v in fields.items()}}})
            out.append(cd)
        return NS(candidates=out)


class _TaskRun:
    def __init__(self, p: "FakeParallel") -> None:
        self.p = p
        self.ids = count(1)
        self.step_of: dict[str, str] = {}
        self.pending_408: dict[str, int] = {}

    def create(self, **req: Any) -> NS:
        rid = f"trun_{next(self.ids)}"
        step = req["metadata"]["step"]
        self.p.journal.append(("parallel", f"task_run.create({step})", req["metadata"]["company"]))
        self.p.requests.append((f"task_run.create({step})", req))
        self.step_of[rid] = step
        self.pending_408[rid] = self.p.task_408s
        return NS(run_id=rid, status="queued")

    def result(self, run_id: str, api_timeout: int = 600, timeout: float = 600) -> NS:
        self.p.result_windows.append(api_timeout)
        step = self.step_of[run_id]
        if self.pending_408[run_id] > 0:
            self.pending_408[run_id] -= 1
            self.p.on_408()
            raise FakeAPIStatusError(408)
        if step in self.p.task_failures:
            raise FakeAPIStatusError(404)
        errors = self.p.task_result_errors.get(step)
        if errors:
            raise FakeAPIStatusError(errors.pop(0))
        content = self.p.brief_content if step == "brief" else self.p.team_content
        return NS(run=NS(run_id=run_id, status="completed"),
                  output=NS(type="json", content=content, basis=self.p.brief_basis if step == "brief" else []))

    def retrieve(self, run_id: str) -> NS:
        if run_id not in self.step_of:
            raise FakeAPIStatusError(404)
        failed = self.step_of[run_id] in self.p.task_failures
        return NS(run_id=run_id, status="failed" if failed else "running",
                  error=NS(message="processor error") if failed else None)


class _TaskGroup:
    def __init__(self, p: "FakeParallel") -> None:
        self.p = p
        self.ids = count(1)
        self.inputs: dict[str, list[dict[str, Any]]] = {}

    def create(self, metadata: dict[str, Any] | None = None) -> NS:
        gid = f"tgrp_{next(self.ids)}"
        self.p.journal.append(("parallel", "task_group.create", (metadata or {}).get("company")))
        self.inputs[gid] = []
        return NS(task_group_id=gid)

    def add_runs(self, gid: str, inputs: list[dict[str, Any]], default_task_spec: dict[str, Any]) -> NS:
        self.p.journal.append(("parallel", "task_group.add_runs", len(inputs)))
        self.p.requests.append(("task_group.add_runs", {"inputs": inputs, "default_task_spec": default_task_spec}))
        self.inputs[gid].extend(inputs)
        return NS(run_ids=[f"trun_g{i}" for i in range(len(inputs))])

    def retrieve(self, gid: str) -> NS:
        n = len(self.inputs[gid])
        return NS(status=NS(is_active=False, num_task_runs=n, task_run_status_counts={"completed": n} if n else {}))

    def get_runs(self, gid: str, include_input: bool = False, include_output: bool = False) -> list[NS]:
        events = []
        # Reverse order on purpose: the loop must join on metadata.row_id, not stream order.
        for i, inp in reversed(list(enumerate(self.inputs[gid]))):
            name = inp["input"]["person_name"]
            ped = self.p.pedigree_by_name.get(name)
            if ped is None:
                events.append(NS(type="task_run.state", run=NS(run_id=f"trun_g{i}", status="failed",
                                                                metadata=inp["metadata"]), output=None))
                continue
            content, conf = ped
            events.append(NS(type="task_run.state",
                             run=NS(run_id=f"trun_g{i}", status="completed", metadata=inp["metadata"]),
                             output=NS(type="json", content=content,
                                       basis=[basis(k, v, (f"https://profiles.example.com/{i}/{k}",))
                                              for k, v in conf.items()])))
        return events


class FakeParallel:
    def __init__(self, journal: list[tuple[str, str, Any]] | None = None) -> None:
        self.journal = journal if journal is not None else []
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.result_windows: list[int] = []
        self.monitor = _Monitor(self)
        self.beta = NS(findall=_FindAll(self))
        self.task_run = _TaskRun(self)
        self.task_group = _TaskGroup(self)
        # knobs
        self.findall_active_polls: int | None = None  # None = done at once; -1 = never done
        self.findall_enrich_active_polls: int | None = None  # the same, after an enrich request
        self.findall_candidates: list[NS] = []
        self.findall_enrichment: dict[str, dict[str, Any]] = {}  # candidate_id -> enrichment fields
        self.brief_content: dict[str, Any] | None = None
        self.brief_basis: list[NS] = []
        self.team_content: dict[str, Any] | None = None
        self.task_failures: set[str] = set()
        self.task_result_errors: dict[str, list[int]] = {}  # step -> HTTP codes /result raises first
        self.task_408s = 0
        self.on_408: Callable[[], None] = lambda: None
        self.pedigree_by_name: dict[str, tuple[dict[str, Any], dict[str, str | None]]] = {}
        self.search_results: dict[str, list[NS]] = {}  # objective substring -> Search API results

    def search(self, objective: str, search_queries: list[str], mode: str = "advanced",
               advanced_settings: dict[str, Any] | None = None) -> NS:
        self.journal.append(("parallel", "search", objective))
        self.requests.append(("search", {"objective": objective, "search_queries": search_queries, "mode": mode,
                                         "advanced_settings": advanced_settings}))
        hits = next((v for k, v in self.search_results.items() if k in objective), [])
        return NS(search_id="search_1", results=list(hits))

    def billed_calls(self) -> list[tuple[str, str, Any]]:
        billed = {"monitor.create", "findall.create", "findall.enrich", "task_run.create(brief)",
                  "task_run.create(team)", "task_group.create", "search"}
        return [j for j in self.journal if j[0] == "parallel" and j[1] in billed]


# ---- FakeBackend ----------------------------------------------------------------------------
def leaders_part_missing(payload: dict[str, Any]) -> bool:
    """The backend's ``missing_talent``: the leaders' part of Talent is null (``talent_leaders``
    on a blended card, ``talent`` on a legacy one with no ``talent_basis``)."""
    scores = payload.get("scores") or {}
    if scores.get("talent_basis") is None:
        return scores.get("talent") is None
    return scores.get("talent_leaders") is None


def scores_problem(scores: Any) -> str | None:
    """The backend's ``LaunchRadarScores`` consistency rule, or None when the breakdown adds up.
    Only the talent breakdown is checked here (the fake does not validate whole payloads)."""
    if not isinstance(scores, dict):
        return None
    talent, lead, team = scores.get("talent"), scores.get("talent_leaders"), scores.get("talent_team")
    basis = scores.get("talent_basis")
    if basis is None:
        ok = lead is None and team is None
    elif basis == "both":
        ok = lead is not None and team is not None and talent == lead + team
    elif basis == "leaders":
        ok = lead is not None and team is None and talent == 2 * lead
    elif basis == "team":
        ok = team is not None and lead is None and talent == 2 * team
    else:
        ok = False
    return None if ok else f"inconsistent talent breakdown: {basis} {talent} = {lead} + {team}"


class FakeBackend:
    def __init__(self, journal: list[tuple[str, str, Any]] | None = None, cap: float = 5.0) -> None:
        self.journal = journal if journal is not None else []
        self.cap = cap
        self.runs: dict[str, dict[str, Any]] = {}
        self.spend: list[dict[str, Any]] = []
        self.monitors: dict[str, dict[str, Any]] = {}
        self.cards: dict[str, dict[str, Any]] = {}  # domain -> row
        self.tracked_names: dict[str, str] = {}  # lower(display_name) -> company id
        self.tracked_boards: dict[tuple[str, str], str] = {}  # (ats, lower(token)) -> company id
        self.requests: list[httpx.Request] = []
        self.card_queries: list[dict[str, Any]] = []  # each GET /cards page: statuses, after_id, limit
        self.card_ids = count(1)
        self.run_ids = count(1)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: self.handle(request))

    # helpers
    def total(self) -> float:
        return round(sum(s["amount_usd"] for s in self.spend), 6)

    def run_spend(self, run_id: int) -> float:
        return round(sum(s["amount_usd"] for s in self.spend if s["run_id"] == run_id), 6)

    def add_monitor(self, slot: str, monitor_id: str, *, charged_through: str, last_event_id: str | None = None,
                    status: str = "active") -> None:
        self.monitors[slot] = {"slot": slot, "monitor_id": monitor_id, "query": "q", "processor": "base",
                               "frequency": "1d", "status": status, "last_event_id": last_event_id,
                               "charged_through": charged_through}

    @staticmethod
    def _json(status: int, body: Any) -> httpx.Response:
        return httpx.Response(status, json=body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        assert path.startswith(PREFIX), path
        path = path[len(PREFIX):]
        method = request.method
        body = json.loads(request.content) if request.content else None
        parts = path.strip("/").split("/")

        if method == "POST" and parts == ["runs"]:
            uid = body["run_uuid"]
            if uid not in self.runs:
                self.runs[uid] = {"id": next(self.run_ids), "status": "running", "budget": body["budget_usd"],
                                  "events_read": 0, "cards_posted": 0, "notes": None, "host": body["host"]}
            r = self.runs[uid]
            self.journal.append(("backend", "start_run", uid))
            return self._json(201, {"run_id": r["id"], "run_uuid": uid, "budget_usd": r["budget"],
                                    "run_spend_usd": self.run_spend(r["id"]), "total_spend_usd": self.total(),
                                    "cap_usd": self.cap, "remaining_usd": round(self.cap - self.total(), 6),
                                    "monitors": [m for m in self.monitors.values() if m["status"] == "active"]})
        if method == "POST" and len(parts) == 3 and parts[0] == "runs" and parts[2] == "reserve":
            r = self.runs.get(parts[1])
            if r is None:
                return self._json(404, {"detail": "run not found"})
            if r["status"] != "running":
                return self._json(409, {"detail": "run not running"})
            est = float(body["est_usd"])
            assert 0 < est <= 1, est
            rs, tot = self.run_spend(r["id"]), self.total()
            if not body["accrued"]:
                if rs + est > r["budget"] + 1e-9:
                    self.journal.append(("backend", "refused", body["step"]))
                    return self._json(402, {"detail": {"reason": "run_budget", "run_spend_usd": rs,
                                                       "total_spend_usd": tot, "cap_usd": self.cap}})
                if tot + est > self.cap + 1e-9:
                    self.journal.append(("backend", "refused", body["step"]))
                    return self._json(402, {"detail": {"reason": "cap", "run_spend_usd": rs,
                                                       "total_spend_usd": tot, "cap_usd": self.cap}})
            self.spend.append({"run_id": r["id"], "step": body["step"], "domain": body["domain"],
                               "amount_usd": est, "accrued": body["accrued"]})
            self.journal.append(("backend", "reserve", body["step"]))
            return self._json(200, {"reserved_usd": est, "run_spend_usd": self.run_spend(r["id"]),
                                    "total_spend_usd": self.total(), "cap_usd": self.cap,
                                    "over_cap": tot + est > self.cap + 1e-9})
        if method == "POST" and len(parts) == 3 and parts[0] == "runs" and parts[2] == "finish":
            r = self.runs.get(parts[1])
            if r is None:
                return self._json(404, {"detail": "run not found"})
            if r["status"] != "running":
                return self._json(409, {"detail": "run already finished"})
            r.update(status=body["status"], events_read=body["events_read"], cards_posted=body["cards_posted"],
                     notes=body["notes"])
            self.journal.append(("backend", "finish", body["status"]))
            return self._json(200, {"run_id": r["id"], "status": r["status"], "run_spend_usd": self.run_spend(r["id"]),
                                    "total_spend_usd": self.total()})
        if method == "GET" and parts == ["monitors"]:
            return self._json(200, {"monitors": list(self.monitors.values())})
        if method == "PUT" and parts[0] == "monitors":
            self.monitors[parts[1]] = {"slot": parts[1], "last_event_id": None, **body}
            self.journal.append(("backend", "put_monitor", parts[1]))
            return self._json(200, self.monitors[parts[1]])
        if method == "PATCH" and parts[0] == "monitors":
            if parts[1] not in self.monitors:
                return self._json(404, {"detail": "no such monitor"})
            self.monitors[parts[1]].update(body)
            self.journal.append(("backend", "patch_monitor", (parts[1], tuple(sorted(body)))))
            return self._json(200, self.monitors[parts[1]])
        if method == "GET" and parts == ["seen"]:
            q = parse_qs(request.url.query.decode())
            doms, names = q.get("domain", []), q.get("name", [])
            if len(doms) > 100 or len(names) > 100:
                return self._json(422, {"detail": "too many"})
            out_d = {}
            for d in doms:
                nd = normalize_domain(d)
                if nd in self.cards:
                    out_d[nd] = {"card_id": self.cards[nd]["id"], "status": self.cards[nd]["status"]}
            out_n = {n: self.tracked_names[n.lower()] for n in names if n.lower() in self.tracked_names}
            return self._json(200, {"domains": out_d, "names": out_n})
        if method == "POST" and parts == ["cards"]:
            r = self.runs.get(body["run_uuid"])
            if r is None:
                return self._json(404, {"detail": "run not found"})
            if r["status"] != "running":
                return self._json(409, {"detail": "run not running"})
            p = body["payload"]
            if normalize_domain(p["domain"]) != p["domain"]:
                return self._json(422, {"detail": "domain not normalized"})
            if (bad := scores_problem(p.get("scores"))) is not None:
                return self._json(422, {"detail": bad})
            if p["domain"] in self.cards:
                self.journal.append(("backend", "post_card_409", p["domain"]))
                return self._json(409, {"detail": "domain already posted"})
            tok = (p["ats"].get("board_token") or "").lower()
            tracked = self.tracked_boards.get((p["ats"]["provider"], tok)) if tok else None
            cid = next(self.card_ids)
            self.cards[p["domain"]] = {"id": cid, "status": "new", "payload": p, "tracked_company_id": tracked}
            r["cards_posted"] += 1
            self.journal.append(("backend", "post_card", p["domain"]))
            return self._json(201, {"id": cid, "tracked_company_id": tracked})
        if method == "GET" and parts == ["cards"]:
            q = parse_qs(request.url.query.decode())
            doms = {normalize_domain(d) for d in q.get("domain", [])}
            missing = q.get("missing_talent", ["false"])[0] == "true"
            every = q.get("all", ["false"])[0] == "true"
            statuses = set(q.get("status", [])) or {"new", "saved", "archived"}
            after_id = int(q.get("after_id", ["0"])[0])
            limit = int(q.get("limit", ["100"])[0])
            if not doms and not missing and not every:
                return self._json(422, {"detail": "give at least one domain, missing_talent=true or all=true"})
            self.card_queries.append({"statuses": statuses, "after_id": after_id, "limit": limit, "all": every})
            if not statuses <= {"new", "saved", "archived"} or not 1 <= limit <= 500:
                return self._json(422, {"detail": "bad status or limit"})
            rows = sorted(((d, r) for d, r in self.cards.items() if r["status"] in statuses
                           and r["id"] > after_id
                           and (not doms or d in doms)
                           and (not missing or leaders_part_missing(r["payload"]))),
                          key=lambda dr: dr[1]["id"])[:limit]
            return self._json(200, {"cards": [{"id": r["id"], "domain": d, "status": r["status"],
                                               "payload": r["payload"]} for d, r in rows]})
        if method == "PUT" and len(parts) == 3 and parts[0] == "cards" and parts[2] == "payload":
            hit = next(((d, r) for d, r in self.cards.items() if r["id"] == int(parts[1])), None)
            if hit is None or hit[1]["status"] == "deleted":
                return self._json(404, {"detail": "card not found"})
            if body["payload"]["domain"] != hit[0]:
                return self._json(422, {"detail": "payload domain is not the card's domain"})
            if (bad := scores_problem(body["payload"].get("scores"))) is not None:
                return self._json(422, {"detail": bad})
            hit[1]["payload"] = body["payload"]
            self.journal.append(("backend", "put_payload", hit[0]))
            return self._json(200, {"id": hit[1]["id"], "domain": hit[0], "status": hit[1]["status"],
                                    "posted_at": "x", "updated_at": "y"})
        return self._json(404, {"detail": f"unrouted {method} {path}"})


def ats_transport(boards: dict[str, tuple[int, Any]]) -> httpx.MockTransport:
    """Public ATS APIs: ``{url: (status, json_body)}``; anything else is a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        hit = boards.get(str(request.url))
        if hit is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(hit[0], json=hit[1])

    return httpx.MockTransport(handler)
