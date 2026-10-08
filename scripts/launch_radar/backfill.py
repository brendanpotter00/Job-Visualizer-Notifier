"""``radar.py backfill``: a one-off FindAll sweep of the past ``--days`` days.

Monitors only report what happens after they are created, so this fills that gap
once. One FindAll run (``entity_type="companies"``, generator ``base``) finds
early-stage startups that announced a round or a launch inside the window, one
``base`` enrichment turns every match into an event shaped like a Monitor event,
and then the events take the same path as in ``run``: domain lookup, dedupe and
the local queue. The next ``radar.py run --max-companies N`` researches them.

Spend: ``fixed + per_match x limit`` is reserved before the create and
``enrich price x matches`` before the enrich, in rows of at most $1 (the backend's
limit for one reservation). The FindAll id and every reservation are saved to
``backfill.json`` before the next step, so a re-run after a crash or the deadline
resumes polling and never creates (or reserves) a second FindAll run.

FindAll candidates and enrichment values are web data: only the known fields are
copied, as clipped strings and http(s) URLs, and nothing in them is acted on.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .ats import safe_http_url
from .card import announced_on, as_text, parse_date
from .domains import is_hostname, normalize_domain
from .leaders import POLL_INTERVAL_S, Deadline, poll_findall
from .monitors import APP_TAG
from .parallel_client import status_code_of
from .pipeline import (
    BACKFILL_SLOT,
    EXIT_ERROR,
    EXIT_OK,
    Deps,
    RunCounters,
    admin_run,
    dedupe,
)
from .resolve import (
    MAX_LOOKUPS_PER_RUN,
    SEARCH_PRICE,
    is_listing_site,
    resolve_missing_domains,
)
from .schemas import FINDALL_PRICE, TASK_PRICE, backfill_event_schema, ceil_cost
from .state import iso

ORIGIN = "findall_backfill"  # the card's event.origin
SLOT = BACKFILL_SLOT  # the queue item's slot (Monitor events carry their Monitor's slot); never dropped as stale
ENTITY_TYPE = "companies"
GENERATORS = ("preview", "base", "core")  # pro's $10 fixed fee is over the backend's $5 run budget
ENRICH_PROCESSOR = "base"
CREATE_STEP = "findall.create(backfill)"
ENRICH_STEP = "findall.enrich(backfill)"
CONDITION_STARTUP = "early_stage_startup_check"
CONDITION_RECENT = "recent_announcement_check"
ENRICHED_MARKERS = ("headline", "event_type")  # required, non-null enrichment fields
MAX_RESERVE_USD = 1.0  # the backend refuses one reservation above $1
MAX_RUN_BUDGET_USD = 5.0  # the backend refuses a run budget above $5
PREVIEW_MAX_LIMIT = 10  # preview evaluates 5-10 candidates
ENRICH_GRACE_S = 300.0  # once the run is idle, wait this long after the enrich request for every match's fields


@dataclass
class BackfillOptions:
    days: int = 30
    limit: int = 20
    generator: str = "base"
    exclude: frozenset[str] = frozenset()
    deadline_s: float = 540.0
    dry_run: bool = False
    new: bool = False


# ---- requests and estimates ------------------------------------------------------------
def window(now: datetime, days: int) -> tuple[str, str]:
    """``(start, end)`` as ISO dates: today in UTC and ``days`` before it, both inclusive."""
    end = now.astimezone(timezone.utc).date()
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def create_request(start: str, end: str, generator: str, limit: int) -> dict[str, Any]:
    span = f"between {start} and {end} (inclusive)"
    return {
        "objective": (f"FindAll early-stage startups that publicly announced a newly closed pre-seed, seed, "
                      f"Series A or Series B funding round, or a notable new product launch, {span}."),
        "entity_type": ENTITY_TYPE,
        "match_conditions": [
            {"name": CONDITION_STARTUP, "description": (
                "The company is an independent, privately held early-stage startup (roughly pre-seed to Series B). "
                "It is NOT a large or established technology company (such as Google, Apple, Microsoft, Amazon, "
                "Meta, Nvidia, OpenAI or Anthropic), NOT a publicly traded company, and NOT a subsidiary, division "
                "or product of a larger company. Evidence: the company's own website, its funding announcements, "
                "startup databases or news coverage. If there is no evidence that it is an independent startup, "
                "the condition is not satisfied.")},
            {"name": CONDITION_RECENT, "description": (
                f"The company publicly announced, {span}, EITHER a newly closed pre-seed, seed, Series A or "
                f"Series B venture funding round OR a notable new product launch. The announcement itself (the "
                f"press release, the company's own post, or the first news report) must be dated {span}; an "
                f"article inside the window about an older round or launch does not count. Acquisitions, IPOs, "
                f"debt, grants, Series C or later rounds, hiring news and minor feature updates do not match. If "
                f"the announcement date cannot be confirmed to fall {span}, the condition is not satisfied.")},
        ],
        "generator": generator,
        "match_limit": limit,
        "metadata": {"app": APP_TAG, "step": "backfill", "window": f"{start}..{end}"},
    }


def enrich_request(start: str, end: str) -> dict[str, Any]:
    return {"processor": ENRICH_PROCESSOR,
            "output_schema": {"type": "json", "json_schema": backfill_event_schema(start, end)}}


def create_estimate(generator: str, limit: int) -> float:
    fixed, per_match = FINDALL_PRICE[generator]
    return ceil_cost(fixed + per_match * limit)


def enrich_estimate(matches: int) -> float:
    return ceil_cost(TASK_PRICE[ENRICH_PROCESSOR] * matches)


def run_budget(generator: str, limit: int) -> float:
    """The most one invocation can reserve (the create, an enrichment and a domain lookup for
    every possible match), rounded up to the cent. It is the backend run's budget."""
    most = create_estimate(generator, limit) + enrich_estimate(limit) + limit * SEARCH_PRICE
    return math.ceil(round(most * 100, 6)) / 100


def chunks(est: float) -> list[float]:
    """``est`` split into reservations of at most ``MAX_RESERVE_USD``."""
    parts: list[float] = []
    left = round(est, 6)
    while left > 0:
        part = min(MAX_RESERVE_USD, left)
        parts.append(ceil_cost(part))
        left = round(left - part, 6)
    return parts


# ---- parsing the enriched matches ---------------------------------------------------------
def usd_text(v: Any) -> str | None:
    """``amount_usd`` as written; a bare number (``15000000.0``) becomes ``$15M``."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if not math.isfinite(v) or v <= 0:
            return None
        for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if v >= size:
                return "$" + f"{v / size:.2f}".rstrip("0").rstrip(".") + suffix
        return f"${v:,.0f}"
    return as_text(v, 40)


def own_domain(v: Any) -> str | None:
    """The normalized domain when it can be the company's own site (not a news or directory host).
    Big tech is kept, so dedupe reports it as "big tech"."""
    dom = normalize_domain(v)
    return dom if dom and is_hostname(dom) and not is_listing_site(dom) else None


def _value(output: dict[str, Any], key: str) -> Any:
    """``output[key]`` is ``{"value": ..., "type": "enrichment"}``; older results hold the bare value."""
    v = output.get(key)
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _attr(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _announcement_citation(cd: Any) -> str | None:
    """The first cited URL behind the recent-announcement match condition."""
    for b in _attr(cd, "basis") or []:
        if _attr(b, "field") != CONDITION_RECENT:
            continue
        for c in _attr(b, "citations") or []:
            url = safe_http_url(_attr(c, "url"))
            if url:
                return url
    return None


def matched(result: Any) -> list[Any]:
    return [cd for cd in (_attr(result, "candidates") or []) if _attr(cd, "match_status") == "matched"]


def is_enriched(cd: Any) -> bool:
    out = _attr(cd, "output")
    return isinstance(out, dict) and any(k in out for k in ENRICHED_MARKERS)


def match_to_event(cd: Any, start: date, end: date, findall_id: str) -> tuple[dict[str, Any] | None, str]:
    """The Monitor-shaped event for one matched candidate, or ``(None, skip reason)``.

    The keys are ``monitors.EVENT_FIELDS`` plus ``event_id``, ``event_date`` and ``slot`` (as
    a Monitor event), ``origin`` and ``findall_id``. A row dated outside the window is
    dropped; an undated row is kept, because the match condition already checked the date.
    """
    out = _attr(cd, "output")
    out = out if isinstance(out, dict) else {}
    if not any(k in out for k in ENRICHED_MARKERS):
        return None, "not enriched"
    announced = parse_date(_value(out, "announced_at"))
    if announced is not None and not start <= announced <= end:
        return None, "announced outside the window"
    name = as_text(_value(out, "company_name"), 200) or as_text(_attr(cd, "name"), 200)
    if not name:
        return None, "no company name"
    etype = as_text(_value(out, "event_type"), 20)
    ev: dict[str, Any] = {
        "company_name": name,
        "company_domain": None,
        "event_type": etype.lower() if etype else None,
        "round": as_text(_value(out, "round"), 80),
        "amount_usd": usd_text(_value(out, "amount_usd")),
        "investors": as_text(_value(out, "investors"), 300),
        # A date that did not parse may still name a month (``2026-09``); anything else is None.
        "announced_at": announced.isoformat() if announced else announced_on(_value(out, "announced_at")),
        "source_url": safe_http_url(_value(out, "source_url")) or _announcement_citation(cd),
        "headline": as_text(_value(out, "headline"), 300) or as_text(_attr(cd, "description"), 300),
        "event_id": _attr(cd, "candidate_id"),
        "event_date": announced.isoformat() if announced else None,
        "slot": SLOT,
        "origin": ORIGIN,
        "findall_id": findall_id,
    }
    for source, raw in (("enrichment", _value(out, "company_domain")), ("findall_url", _attr(cd, "url"))):
        dom = own_domain(raw)
        if dom:
            ev.update(company_domain=dom, domain_source=source)
            break
    return ev, ""


# ---- the command ------------------------------------------------------------------------
def _new_state(opts: BackfillOptions, now: datetime) -> dict[str, Any]:
    start, end = window(now, opts.days)
    return {"days": opts.days, "match_limit": opts.limit, "generator": opts.generator,
            "window": {"start": start, "end": end}, "findall_id": None, "reserved": {}, "attempts": {},
            "matches": None, "enrich_requested": False, "enrich_requested_at": None,
            "started_at": iso(now), "finished_at": None}


def _settings(st: dict[str, Any]) -> str:
    return (f"window {st['window']['start']}..{st['window']['end']} · generator {st['generator']} "
            f"· limit {st['match_limit']}")


def backfill(opts: BackfillOptions, deps: Deps) -> int:
    log = deps.log
    if opts.generator not in GENERATORS:
        log(f"backfill: --generator must be one of {', '.join(GENERATORS)}")
        return EXIT_ERROR
    if opts.generator == "preview" and opts.limit > PREVIEW_MAX_LIMIT:
        log(f"backfill: --generator preview takes --limit 5..{PREVIEW_MAX_LIMIT} (candidates evaluated)")
        return EXIT_ERROR

    st = deps.store.load_backfill()
    if st is not None and st.get("finished_at") and not opts.new:
        log(f"backfill: {st.get('findall_id')} finished at {st['finished_at']} ({st.get('notes') or 'no notes'}); "
            f"pass --new to pay for a new sweep")
        return EXIT_OK
    if st is None or st.get("finished_at"):
        st = _new_state(opts, deps.now())
    elif not st.get("findall_id") and not st["attempts"].get("findall_id"):
        # Nothing reached Parallel yet: take this invocation's settings and today's window. A
        # reservation already made for the same generator and limit is kept (never made twice);
        # for other settings the amounts differ, so it is made again (the ledger over-counts).
        fresh = _new_state(opts, deps.now())
        if (st["generator"], st["match_limit"]) == (fresh["generator"], fresh["match_limit"]):
            fresh["reserved"] = st["reserved"]
        st = fresh
    else:
        log(f"backfill: resuming {st.get('findall_id') or 'an unconfirmed create'} ({_settings(st)}); "
            f"this invocation's --days/--limit/--generator are not used")

    budget = run_budget(st["generator"], st["match_limit"])
    if budget > MAX_RUN_BUDGET_USD:
        log(f"backfill: up to ${budget:.2f} is over the ${MAX_RUN_BUDGET_USD:.2f} run budget; lower --limit")
        return EXIT_ERROR
    if opts.dry_run:
        return _dry_run(st, budget, log)
    counters = RunCounters()
    job = _Backfill(st, opts, deps, counters)
    return admin_run(deps, "backfill", job.run, budget=budget, counters=counters)


def _dry_run(st: dict[str, Any], budget: float, log: Callable[[str], None]) -> int:
    """Prints the request(s) and the estimate. No Parallel call, no backend call, no file write."""
    start, end, gen, limit = st["window"]["start"], st["window"]["end"], st["generator"], st["match_limit"]
    if st.get("findall_id"):
        log(f"dry run: would resume {st['findall_id']} ({_settings(st)}); no new FindAll run")
    else:
        log("dry run: would call client.beta.findall.create(**request), request =\n"
            + json.dumps(create_request(start, end, gen, limit), indent=2))
    if not st.get("enrich_requested"):
        log("dry run: once discovery finishes, would call client.beta.findall.enrich(findall_id, **request), "
            "request =\n" + json.dumps(enrich_request(start, end), indent=2))
    fixed, per_match = FINDALL_PRICE[gen]
    create_est = create_estimate(gen, limit)
    log(f"dry run: FindAll {gen} ${fixed:.2f} + {limit} x ${per_match:.2f} = ${create_est:.3f}, reserved first "
        f"in rows {chunks(create_est)}")
    log(f"dry run: enrichment up to {limit} x ${TASK_PRICE[ENRICH_PROCESSOR]:.3f} = ${enrich_estimate(limit):.3f} "
        f"(reserved for the actual match count before the call); domain lookups up to {limit} x "
        f"${SEARCH_PRICE:.3f}")
    log(f"dry run: at most ${budget:.2f} (the backend run's budget); nothing called, spent or written")
    return EXIT_OK


class _Backfill:
    def __init__(self, st: dict[str, Any], opts: BackfillOptions, deps: Deps, counters: RunCounters) -> None:
        self.st = st
        self.opts = opts
        self.deps = deps
        self.counters = counters
        self.run_uuid = ""

    def save(self) -> None:
        self.deps.store.save_backfill(self.st)

    def reserve(self, step: str, est: float) -> None:
        """Reserve ``est`` in rows of at most $1, each once: a saved row survives a resume."""
        for i, part in enumerate(chunks(est)):
            name = step if i == 0 else f"{step}#{i + 1}"
            if name in self.st["reserved"]:
                continue
            self.deps.backend.reserve(self.run_uuid, name, part)
            self.st["reserved"][name] = part
            self.save()

    def billed(self, step: str, est: float, key: str, call: Callable[[], Any]) -> Any:
        """``CompanyJob.billed`` for the backfill: reserve, call once, save the result under ``key``."""
        if self.st.get(key):
            return self.st[key]
        attempts = self.st["attempts"]
        prior = int(attempts.get(key, 0))
        if prior:
            # The earlier call may have reached Parallel without its result being saved: it may have billed.
            step = f"{step}#retry{prior}"
            self.deps.log(f"backfill: re-sending {step} after an ambiguous failure; the previous attempt may "
                          f"have billed")
        self.reserve(step, est)
        attempts[key] = prior + 1
        self.save()
        try:
            value = call()
        except Exception as e:
            code = status_code_of(e)
            if code is not None and 400 <= code < 500 and code not in (408, 429):
                attempts[key] = prior  # Parallel answered and refused: nothing was created or billed
                self.save()
            raise
        self.st[key] = value
        self.save()
        self.deps.log(f"backfill: {step} -> {value}")
        return value

    def run(self, run_uuid: str) -> str:
        self.run_uuid = run_uuid
        st, d, log = self.st, self.deps, self.deps.log
        start, end = st["window"]["start"], st["window"]["end"]
        gen, limit = st["generator"], st["match_limit"]
        self.save()
        client = d.make_client()
        deadline = Deadline(self.opts.deadline_s, d.clock)
        log(f"backfill: {_settings(st)}")

        fid = str(self.billed(CREATE_STEP, create_estimate(gen, limit), "findall_id",
                              lambda: str(client.beta.findall.create(**create_request(start, end, gen, limit))
                                          .findall_id)))
        if not st["enrich_requested"]:
            status = poll_findall(client, fid, deadline, d.sleep).status
            matches = len(matched(client.beta.findall.result(fid)))
            st["matches"] = matches
            st["discovery"] = f"{getattr(status, 'status', None)} ({getattr(status, 'termination_reason', None)})"
            self.save()
            log(f"backfill {fid}: discovery {st['discovery']}, {matches} match(es)")
            if not matches:
                return self._finish(fid, [], Counter(), searches=0, kept=0)

            def enrich() -> bool:
                client.beta.findall.enrich(fid, **enrich_request(start, end))
                st["enrich_requested_at"] = d.wall()
                return True

            self.billed(ENRICH_STEP, enrich_estimate(matches), "enrich_requested", enrich)
        result = self._wait_enriched(client, fid, deadline)

        skipped: Counter[str] = Counter()
        events: list[dict[str, Any]] = []
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        rows = matched(result)
        self.counters.events_read = len(rows)
        for cd in rows:
            ev, reason = match_to_event(cd, lo, hi, fid)
            if ev is None:
                skipped[reason] += 1
                out = _attr(cd, "output")
                when = as_text(_value(out, "announced_at"), 20) if isinstance(out, dict) else None
                log(f"skip {as_text(_attr(cd, 'name'), 80)!r}: {reason}" + (f" ({when})" if when else ""))
            else:
                events.append(ev)

        searches = 0

        def reserve_search(step: str, est: float) -> Any:
            nonlocal searches
            out = d.backend.reserve(self.run_uuid, step, est)
            searches += 1
            return out

        # Known and accepted: the domain lookups are not recorded in backfill.json, so a re-run
        # after a crash, a 402 or the deadline between here and _finish looks them up (and pays
        # for them) again. Each is $0.005 and still reserved first, so the ledger stays exact;
        # only the few cents are repeated.
        resolve_missing_domains(events, client, reserve_search, log, limit=max(MAX_LOOKUPS_PER_RUN, len(events)))
        queue = d.store.load_queue()
        items = dedupe(events, d.backend, {q["domain"] for q in queue}, self.opts.exclude, d.now(), log,
                       reasons=skipped)
        d.store.append_queue(items)
        return self._finish(fid, items, skipped, searches=searches, kept=len(events))

    def _wait_enriched(self, client: Any, fid: str, deadline: Deadline) -> Any:
        """The result once the run is idle and every match carries the enrichment, or once
        ``ENRICH_GRACE_S`` has passed since the enrich request (the rest are then skipped)."""
        st, d = self.st, self.deps
        if st.get("enrich_requested_at") is None:  # cut off between the enrich call and its save
            st["enrich_requested_at"] = d.wall()
            self.save()
        while True:
            if not client.beta.findall.retrieve(fid).status.is_active:
                result = client.beta.findall.result(fid)
                missing = sum(1 for cd in matched(result) if not is_enriched(cd))
                waited = d.wall() - float(st["enrich_requested_at"])
                if not missing:
                    return result
                if waited >= ENRICH_GRACE_S:
                    d.log(f"backfill {fid}: {missing} match(es) still not enriched after {waited:.0f}s; "
                          f"skipping them")
                    return result
            deadline.check(f"findall {fid} enrichment")
            d.sleep(min(POLL_INTERVAL_S, max(0.0, deadline.remaining())))

    def _finish(self, fid: str, items: list[dict[str, Any]], skipped: Counter[str], *, searches: int,
                kept: int) -> str:
        """Log the summary, mark the backfill finished and return the run's notes."""
        st, log = self.st, self.deps.log
        matches = int(st.get("matches") or 0)
        fixed, per_match = FINDALL_PRICE[st["generator"]]
        enrich_price = TASK_PRICE[ENRICH_PROCESSOR] if st["enrich_requested"] else 0.0
        spent = fixed + per_match * matches + enrich_price * matches + SEARCH_PRICE * searches
        reserved = sum(float(v) for v in st["reserved"].values()) + SEARCH_PRICE * searches
        skips = ", ".join(f"{reason} {n}" for reason, n in skipped.most_common()) or "none"
        log(f"backfill {fid}: {_settings(st)}")
        log(f"backfill {fid}: matched {matches} · kept {kept} · queued {len(items)}")
        log(f"backfill {fid}: skipped: {skips}")
        log(f"backfill {fid}: spend (estimate) FindAll ${fixed:.2f} + {matches} x ${per_match:.2f}, enrichment "
            f"{matches if enrich_price else 0} x ${enrich_price:.3f}, {searches} domain lookup(s) x "
            f"${SEARCH_PRICE:.3f} = ${spent:.3f} (reserved ${reserved:.3f})")
        for it in items:
            ev = it["event"]
            facts = " ".join(str(ev[k]) for k in ("event_type", "round", "amount_usd", "announced_at") if ev.get(k))
            log(f"queued: {it['domain']} ({it['company']}) {facts}".rstrip())
        if items:
            log("next: `radar.sh run --max-companies N` researches the queue, a few companies per run; backfill "
                "items are never dropped as stale")
        notes = (f"{fid}: matched {matches}, kept {kept}, queued {len(items)}; skipped {skips}; "
                 f"est ${spent:.3f}")
        st.update(finished_at=iso(self.deps.now()), notes=notes[:500],
                  summary={"matched": matches, "kept": kept, "queued": len(items), "skipped": dict(skipped),
                           "searches": searches, "est_usd": round(spent, 4), "reserved_usd": round(reserved, 4)})
        self.save()
        return notes
