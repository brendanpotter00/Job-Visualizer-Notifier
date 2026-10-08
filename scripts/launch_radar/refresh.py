"""``radar.py refresh``: re-research the leaders of cards that have none.

A card has no leaders (and so no leaders' part of Talent: ``--missing-talent`` selects
these) when FindAll ``preview`` confirmed no person for it. ``run`` now falls back to the brief's ``founders`` in that case; this
command applies the same fallback to cards posted before it existed. Per card it re-runs
only what that needs:

1. a new brief (Task on ``core``, ``BRIEF_SCHEMA`` with ``founders``), reserved first;
2. when the brief names founders, the pedigree Task Group (one ``base`` run each),
   reserved first;
3. a deterministic rescore and ``PUT /cards/{id}/payload``.

Kept from the card: the event, the team tally (scored again as Talent's team part), the ATS
block, the FindAll id and ``leaders_dropped``. Replaced: the brief's
fields, the leaders, both scores,
the sources, and the issues about the brief, the leaders and the pedigree. ``cost_usd``
and ``timings_s`` add the refresh's own. A card whose new brief fails is left as it was.

Only a card with **no** leaders is refreshed; one that has FindAll leaders is skipped (its
leaders' points cannot be recomputed from the stored card; ``rescore`` carries them), and so is an archived card unless
``--include-archived`` is given. ``GET /cards`` is paged through to the end, so no page cap
hides a card that still needs a refresh behind ones already done. All briefs are reserved and
created first, so they research in parallel, then a pool finishes each card. Like
``run``: a 402 stops new work (exit 2), the deadline saves state (exit 3), a saved id is
never created or reserved again, and in-progress refreshes always resume. A finished card
is recorded in ``refresh_done.json`` and never selected again, so re-running the same
command after exit 3 pays for nothing twice.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .ats import safe_http_url
from .backend_client import BudgetExceeded, CardGone
from .card import announced_on, build_payload
from .domains import is_hostname
from .leaders import BRIEF_LEADERS_ISSUE, MAX_LEADERS, Deadline, DeadlineReached
from .pipeline import (
    EXIT_BUDGET,
    EXIT_ERROR,
    EXIT_INCOMPLETE,
    EXIT_OK,
    PEDIGREE_STEP,
    POST_RESERVE_S,
    CompanyJob,
    Deps,
    Outcome,
)
from .research import brief_request, create_task
from .schemas import TASK_PRICE, ceil_cost
from .state import iso

BRIEF_STEP = "task_run.create(brief)"
BRIEF_EST = ceil_cost(TASK_PRICE["core"])
PEDIGREE_PER_LEADER = TASK_PRICE["base"]
TYPICAL_FOUNDERS = 3  # for the dry run's middle estimate; the real count comes from each brief
REFRESH_WORKERS = 12  # each worker only long-polls Parallel; enough to finish a dozen cards inside one deadline
# Issues about the parts a refresh replaces. The rest (team tally, ATS check, FindAll status) still hold.
REPLACED_ISSUES = ("no leaders confirmed", "leaders from the brief", "brief ", "pedigree", "leader ")


# The card statuses a refresh selects: an archived card was set aside, so paying to refresh it
# needs --include-archived.
DEFAULT_STATUSES = ("new", "saved")
ALL_STATUSES = ("new", "saved", "archived")


@dataclass
class RefreshOptions:
    domains: frozenset[str] = frozenset()
    missing_talent: bool = False
    include_archived: bool = False
    budget: float = 1.0
    deadline_s: float = 540.0
    dry_run: bool = False


# ---- the payload ---------------------------------------------------------------------------
def refreshed_payload(
    old: dict[str, Any],
    *,
    brief: dict[str, Any],
    brief_basis: list[Any],
    leaders: list[tuple[Any, dict[str, Any] | None]],
    run_ids: dict[str, str | None],
    added_cost: float,
    timings: dict[str, float],
    issues: list[str],
    generated_at: str,
) -> dict[str, Any]:
    """The card's new payload: ``old`` with a new brief, new leaders and both scores redone."""
    kept_issues = [i for i in old.get("issues") or [] if isinstance(i, str) and not i.startswith(REPLACED_ISSUES)]
    new = build_payload(
        company=old["company"], domain=old["domain"], monitor_event=None, brief=brief, brief_basis=brief_basis,
        leaders=leaders, leaders_dropped=int(old.get("leaders_dropped") or 0),
        # The stored tally goes back in (build_team_stats is idempotent) so the new Talent includes the team.
        team=old.get("team_stats"), ats=old["ats"],
        run_ids={**(old.get("parallel_run_ids") or {}), **run_ids},
        cost_usd=float(old.get("cost_usd") or 0) + added_cost,
        timings={**(old.get("timings_s") or {}), **timings},
        issues=list(dict.fromkeys(kept_issues + issues)), generated_at=generated_at,
    )
    if isinstance(old.get("event"), dict):
        # Kept as it was, except the date, which the backend now accepts only as an ISO date
        # (or year-month): a card posted before that rule is normalized here, never rejected.
        new["event"] = {**old["event"], "announced_at": announced_on(old["event"].get("announced_at"))}
    if not safe_http_url(brief.get("website_url")) and old.get("website"):
        new["website"] = old["website"]
    new["careers_url"] = new["careers_url"] or old.get("careers_url")
    return new


# ---- one card ---------------------------------------------------------------------------------
class RefreshJob(CompanyJob):
    """``CompanyJob``'s reserve-once / create-once / resume machinery over ``refresh/<domain>.json``."""

    def __init__(self, card: dict[str, Any], run_uuid: str, client: Any, deps: Deps, deadline: Deadline,
                 stop: threading.Event) -> None:
        payload = card["payload"]
        super().__init__({"domain": card["domain"], "company": payload["company"], "event": payload.get("event")},
                         run_uuid, client, deps, deadline, stop)
        self.card = card

    def save(self) -> None:
        self.deps.store.save_refresh(self.domain, self.st)

    def load(self) -> dict[str, Any] | None:
        return self.deps.store.load_refresh(self.domain)

    def new_state(self) -> dict[str, Any]:
        # The card as it was when the refresh started: a resume rebuilds from this snapshot.
        return {**super().new_state(), "card": {"id": self.card["id"], "status": self.card.get("status"),
                                                "payload": self.card["payload"]}}

    def _create_brief(self) -> str:
        headline = (self.item.get("event") or {}).get("headline")
        return self.billed(BRIEF_STEP, BRIEF_EST, "brief_run_id",
                           lambda: create_task(self.client, brief_request(self.company, self.domain, headline)))

    def start(self) -> Outcome | None:
        """Phase 1: reserve and create the brief. ``None`` once it exists (saved), else an outcome."""
        not_started = self.open_state()
        if not_started is not None:
            return not_started
        try:
            self._create_brief()
        except BudgetExceeded as e:
            self.stop.set()
            return Outcome(self.domain, "budget", str(e))
        except Exception as e:  # the company keeps its state (an ambiguous create is reserved again)
            return Outcome(self.domain, "error", f"{type(e).__name__}: {e}"[:300])
        return None

    def _finish(self, outcome: str, talent: Any = None) -> None:
        self.deps.store.mark_refresh_done(self.domain, {"card_id": self.st["card"]["id"], "outcome": outcome,
                                                       "talent": talent, "at": iso(self.deps.now())})
        self.deps.store.delete_refresh(self.domain)

    def _research(self) -> Outcome:
        d = self.deps
        old: dict[str, Any] = self.st["card"]["payload"]
        card_id = int(self.st["card"]["id"])
        brief_id = self._create_brief()
        timings: dict[str, float] = {}
        brief, brief_basis = self._wait("brief_run_id", brief_id, "brief", timings)
        added = sum(float(v) for v in self.st["reserved"].values())
        if brief is None:
            self._finish("unchanged")
            return Outcome(self.domain, "unchanged",
                           f"new brief unusable ({'; '.join(self.st['issues'])}); card {card_id} left as it was; "
                           f"${added:.3f} spent", card_id=card_id)
        leaders = self.leaders_from_brief(brief)
        dropped = int(old.get("leaders_dropped") or 0)
        suffix = f"; {dropped} company page(s) dropped" if dropped else ""
        self.issue((BRIEF_LEADERS_ISSUE if leaders else "no leaders confirmed") + suffix)
        pedigree = self.run_pedigree(leaders, timings)
        if self.deadline.remaining() < POST_RESERVE_S:
            raise DeadlineReached("saving the refreshed card")
        added = sum(float(v) for v in self.st["reserved"].values())
        payload = refreshed_payload(
            old, brief=brief, brief_basis=brief_basis,
            leaders=[(cd, pedigree.get(i)) for i, cd in enumerate(leaders)],
            run_ids={"brief_run_id": brief_id, "pedigree_group_id": self.st["ids"].get("pedigree_group_id")},
            added_cost=added, timings=timings, issues=list(self.st["issues"]), generated_at=iso(d.now()),
        )
        try:
            d.backend.put_payload(card_id, payload)
        except CardGone:
            self._finish("gone")
            return Outcome(self.domain, "gone", f"card {card_id} was deleted; refresh discarded "
                                                f"(${added:.3f} spent)", card_id=card_id)
        talent = payload["scores"]["talent"]
        self._finish("refreshed", talent)
        return Outcome(self.domain, "refreshed", f"{len(leaders)} leader(s) from the brief · talent {talent} "
                                                 f"vc {payload['scores']['vc']} · +${added:.3f}", card_id=card_id)


# ---- selection ------------------------------------------------------------------------------
def select(opts: RefreshOptions, deps: Deps) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(new cards to refresh, in-progress refresh states)``. Free: ``GET /cards`` and local files."""
    log, store = deps.log, deps.store
    in_progress = {d: st for d in store.refresh_domains() if (st := store.load_refresh(d))}
    done = store.load_refresh_done()
    statuses = ALL_STATUSES if opts.include_archived else DEFAULT_STATUSES
    cards = deps.backend.cards(domains=sorted(opts.domains), missing_talent=opts.missing_talent, statuses=statuses)
    for dom in sorted(opts.domains - {c["domain"] for c in cards}):
        log(f"skip {dom}: no live card" if opts.include_archived
            else f"skip {dom}: no new or saved card (an archived one needs --include-archived)")
    fresh: list[dict[str, Any]] = []
    for card in cards:
        dom, payload = card.get("domain"), card.get("payload")
        if not isinstance(dom, str) or not is_hostname(dom) or not isinstance(payload, dict) \
                or not payload.get("company") or not isinstance(payload.get("ats"), dict):
            log(f"skip card {card.get('id')}: unusable domain or payload")
            continue
        leaders = payload.get("leaders") or []
        if dom in in_progress:
            continue  # resumes below
        elif dom in done:
            rec = done[dom]
            log(f"skip {dom}: refreshed at {rec.get('at')} ({rec.get('outcome')}, talent {rec.get('talent')}); "
                f"remove it from {store.refresh_done_path.name} to pay for another refresh")
        elif leaders:
            log(f"skip {dom}: has {len(leaders)} leader(s) from FindAll; refresh only re-researches cards with none")
        else:
            fresh.append(card)
    return fresh, list(in_progress.values())


def _remaining_estimate(st: dict[str, Any] | None) -> tuple[float, float, float]:
    """(low, typical, high) still to reserve for one card: the brief unless reserved, then the
    pedigree unless reserved (exact once the brief's founders are known)."""
    reserved = (st or {}).get("reserved") or {}
    brief = 0.0 if BRIEF_STEP in reserved else BRIEF_EST
    if PEDIGREE_STEP in reserved:
        return brief, brief, brief
    known = (st or {}).get("brief_leaders")
    if known is not None:
        exact = ceil_cost(len(known) * PEDIGREE_PER_LEADER) if known else 0.0
        return brief + exact, brief + exact, brief + exact
    return (brief, brief + ceil_cost(TYPICAL_FOUNDERS * PEDIGREE_PER_LEADER),
            brief + ceil_cost(MAX_LEADERS * PEDIGREE_PER_LEADER))


def _dry_run(fresh: list[dict[str, Any]], resumed: list[dict[str, Any]], deps: Deps) -> int:
    log = deps.log
    low = typical = high = 0.0
    for st in resumed:
        lo, ty, hi = _remaining_estimate(st)
        low, typical, high = low + lo, typical + ty, high + hi
        log(f"would resume: {st.get('domain')} (card {st.get('card', {}).get('id')}); still to reserve "
            f"${lo:.3f}" + (f"-${hi:.3f}" if hi != lo else ""))
    for card in fresh:
        lo, ty, hi = _remaining_estimate(None)
        low, typical, high = low + lo, typical + ty, high + hi
        p = card["payload"]
        log(f"would refresh: {card['domain']} (card {card['id']}, {card.get('status')}) {p.get('company')!r}; "
            f"talent {(p.get('scores') or {}).get('talent')}, {len(p.get('leaders') or [])} leader(s)")
    n = len(fresh) + len(resumed)
    log(f"dry run: {n} card(s): brief ${BRIEF_EST:.3f} each + pedigree ${PEDIGREE_PER_LEADER:.3f} per founder the "
        f"brief names (at most {MAX_LEADERS}): at least ${low:.3f}, about ${typical:.3f} at {TYPICAL_FOUNDERS} "
        f"founders each, at most ${high:.3f}; nothing called, spent or written")
    return EXIT_OK


# ---- the command ------------------------------------------------------------------------------
def refresh(opts: RefreshOptions, deps: Deps) -> int:
    if not opts.domains and not opts.missing_talent:
        deps.log("refresh: give --domains or --missing-talent")
        return EXIT_ERROR
    fresh, resumed = select(opts, deps)
    if opts.dry_run:
        return _dry_run(fresh, resumed, deps)
    if not fresh and not resumed:
        deps.log("refresh: nothing to refresh")
        return EXIT_OK
    run_uuid = uuid.uuid4().hex
    started = deps.backend.start_run(run_uuid, deps.host, opts.budget)
    deps.log(f"refresh: run {started['run_id']} · {len(resumed)} resumed, {len(fresh)} new · spend before "
             f"${float(started['total_spend_usd']):.2f} of ${float(started['cap_usd']):.2f} · budget ${opts.budget:.2f}")
    try:
        code, status, notes = _body(opts, deps, run_uuid, fresh, resumed)
    except BaseException as e:  # incl. SystemExit from the SIGTERM handler: the run row must not stay "running"
        deps.log(f"refresh {run_uuid} failed: {type(e).__name__}: {e}")
        try:
            deps.backend.finish_run(run_uuid, "error", 0, 0, f"refresh: {type(e).__name__}: {e}"[:500])
        except Exception as fin_err:
            deps.log(f"could not finish run {run_uuid}: {type(fin_err).__name__}: {fin_err}")
        raise
    fin = deps.backend.finish_run(run_uuid, status, 0, 0, notes[:500])
    deps.log(f"refresh: {notes} · run ${fin['run_spend_usd']:.3f} · total ${fin['total_spend_usd']:.2f} · {status}")
    return code


def _body(opts: RefreshOptions, deps: Deps, run_uuid: str, fresh: list[dict[str, Any]],
          resumed: list[dict[str, Any]]) -> tuple[int, str, str]:
    deadline = Deadline(opts.deadline_s, deps.clock)
    client = deps.make_client()
    stop = threading.Event()
    jobs = ([RefreshJob(st["card"] | {"domain": st["domain"]}, run_uuid, client, deps, deadline, stop)
             for st in resumed]
            + [RefreshJob(card, run_uuid, client, deps, deadline, stop) for card in fresh])
    outcomes: list[Outcome] = []
    # Phase 1: reserve and create every brief now, so they all research at the same time.
    started: list[RefreshJob] = []
    for job in jobs:
        out = job.start()
        if out is None:
            started.append(job)
        else:
            outcomes.append(out)
    # Phase 2: wait for each brief, run the pedigree, PUT the payload.
    if started:
        # Not a `with` block: on SIGTERM the run must finish at once (see pipeline.run).
        pool = ThreadPoolExecutor(max_workers=min(REFRESH_WORKERS, len(started)))
        try:
            futures = [(job.domain, pool.submit(job.run)) for job in started]
            for domain, fut in futures:
                try:
                    outcomes.append(fut.result())
                except Exception as e:  # reported below; the card keeps its refresh state
                    outcomes.append(Outcome(domain, "error", f"{type(e).__name__}: {e}"[:300]))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    for o in outcomes:
        deps.log(f"{o.status:<11} {o.domain}" + (f" card {o.card_id}" if o.card_id else "")
                 + (f" — {o.detail}" if o.detail else ""))
    statuses = {o.status for o in outcomes}
    notes = "refresh: " + ", ".join(f"{s} {sum(1 for o in outcomes if o.status == s)}" for s in sorted(statuses))
    if "error" in statuses:
        return EXIT_ERROR, "error", notes
    if "budget" in statuses or stop.is_set():
        return EXIT_BUDGET, "stopped", notes
    if statuses & {"deadline", "retry", "not_started"}:
        return EXIT_INCOMPLETE, "stopped", notes
    return EXIT_OK, "ok", notes


__all__ = ["RefreshJob", "RefreshOptions", "refresh", "refreshed_payload", "select"]
