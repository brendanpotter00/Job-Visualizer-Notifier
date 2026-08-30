"""DISCOVERY ORCHESTRATOR — capture the board's API ONCE, prove it replays, then store.

This is the engine that replaced the Stagehand DOM agent. The pivot in one sentence:
instead of paying an LLM to re-read a rendered careers page every 24 hours, we open the
page in a browser **once**, record its network traffic, have Haiku pick the jobs request
and map its fields **once**, synthesize a deterministic recipe, and — the part that
makes it safe — **prove that recipe replays from our production environment before we
promise to track anything**. Runtime never calls an LLM again.

The seven steps, in order, each named because the REFUSE reason is rendered to the user
("we found the feed, but couldn't confirm the results match"):

1. :data:`_STEP_ENTRY` — SSRF-validate the pasted URL (invariant #4, entry half).
2. :data:`_STEP_CAPTURE` — one browser session; record every JSON XHR/fetch.
3. :data:`_STEP_FILTER` — deterministic pre-filter to job-shaped arrays, then
   SSRF-validate every surviving endpoint (invariant #4, discovered-endpoint half).
4. :data:`_STEP_SELECT` — ONE Haiku call: which request, and how its fields map.
5. :data:`_STEP_SYNTHESIZE` — assemble a recipe and run it through
   ``recipe_schema.validate_recipe`` (validate-on-write, invariant #5).
6. :data:`_STEP_ACCEPT` — replay it FROM THE PRODUCTION PATH and check it against the
   capture.
7. accept (store) or **REFUSE** (store nothing).

Because those steps are DETERMINISTIC and known before the run starts, they are also
narrated: :data:`_STEP_TO_CHECKLIST` folds them onto the four user-facing DISCOVERY steps in
:mod:`api.services.discovery.progress`, and ``emit`` publishes the checklist as each one
lands. That is what replaced the "Setting up…" spinner — the run says "found 3 candidate
feeds", "read 90 jobs", or names the exact step it failed at. An accepted run also OPENS
the fifth rung (``first_scan``) that the first harvest closes; discovery never ticks it,
because discovery is not what puts jobs on the row.

**The acceptance gate is the whole point** (plan DECISION D5). Tier 1a (``http_json``
through ``guarded_sync_client`` + ``run_recipe``) is tried first because it costs $0 a
night; tier 1b (``browser_fetch`` in a fresh Chromium) only when 1a's replay fails,
which is what an origin-checked/cookie-gated board looks like from our server (TikTok
400s from httpx and 200s from its own origin). Replaying from HERE — not from the
capture browser — is what catches IP/geo gating and a missing header BEFORE we promise
tracking. Beyond what ``run_recipe`` already enforces (2xx, parses, in-band error keys,
non-empty, ``expected_min_jobs``, the oracle), acceptance adds the one check only
discovery can make: the replayed ids must **overlap the ids the capture browser saw**.
A recipe that returns a hundred rows of something else passes every structural check
and is still the wrong feed.

**A board with no capturable API is REFUSED.** There is no DOM tier to fall back to, by
design (the owner's deterministic-only principle): every runtime path either works or it
does not, decided once, here. Refusing is how we never wrong-track. Two shapes of that,
both learned the hard way: the selector can answer "none of these is a jobs feed"
(:class:`~.request_selector.NoJobsFeedError`) rather than be forced to name something,
and the next-candidate round is only offered arrays at least as job-shaped as the one
that failed — a forced pick of a leftover filter catalogue passes the acceptance gate
trivially, because the gate compares the replay against that same array.

**ACCEPTANCE AND HARVEST ARE TWO DIFFERENT BUDGETS.** Acceptance asks "can we read this
board from our own environment?", which two pages settle as well as a hundred
(:data:`_ACCEPTANCE_MAX_PAGES`, applied by :func:`probe_script` to the very recipe about
to be stored). The nightly harvest asks "read the WHOLE board", so its budget is DERIVED
per board from the board's own declared total and page size (:func:`_harvest_max_pages`)
under a wall-clock ceiling. One constant serving both was a real defect: amazon.jobs
declares ~22,000 jobs, ten pages of its own ten-per-page UI read **97**, and a company
that can never prove it saw the whole board sits at ``health_state='unverified'``
forever. And the PAGE SIZE is itself a recipe parameter — raised toward
:data:`_TARGET_PAGE_SIZE` when the captured request carries one — which turns 1,000
sequential requests into ~100. It is derived from the captured bytes and then PROVEN by
the acceptance replay (:func:`_assert_page_size_honoured`), never assumed: a board that
caps the page silently serves a SHORT page, and a short page is exactly how the sweep
decides the board ended.

**The stored oracle is the completeness CLAIM, and it is deliberately stingy.** A
declared total makes it ``declared_probed`` (the LARGEST total-ish key, never the first
— a per-page count pinned as the total is a confident wrong-close); a real paginated
sweep makes it ``self_consistent``; a single request over a board whose length nobody
published makes it ``none``, which can only ever be UNVERIFIED. Every one of those
mistakes ends the same way if you get it wrong in the generous direction: a nightly run
that certifies a page it never finished reading and closes the rest (invariant #2).

**...and a declared total the board's own facets CONTRADICT is not a total at all**
(:func:`_facet_consensus_total`). amazon.jobs answers ``hits: 10000`` — its
Elasticsearch WINDOW, not its size, while six of its facet blocks agree on 22,621. A
budget big enough to reach that "total" matches it exactly, VERIFIES, and closes 12,621
live jobs. So the guard is not optional decoration on the budget fix; it is the half
that stops the budget fix from creating a confident wrong-close.

NEVER RAISES. Every failure — including an unexpected one — becomes
``DiscoveryOutcome(ok=False, refuse_reason=…)``, because the caller is a ``retry=1``
Procrastinate task whose provisional ``discovering`` row is only cleared by a returned
outcome: an escaping exception wedges that row at "Setting up…" forever.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx

from ..discovery.models import DiscoveryOutcome
from ..discovery.progress import (
    OUTCOME_PARTIAL,
    OUTCOME_REFUSED,
    OUTCOME_TRACKING,
    STEP_FIND_FEED,
    STEP_FIRST_SCAN,
    STEP_OPEN_PAGE,
    STEP_READY,
    STEP_VERIFY_READ,
    ProgressLedger,
    payload_sample,
)
from ..guarded_client import guarded_sync_client
from ..harvest_meta import HarvestEvidence
from ..harvest_verification import HarvestGateError, page_shape_refusal, run_gate
from ..recipe_rows import recipe_rows_to_job_listings
from ..recipe_runner import (
    HARVEST_TIME_BUDGET_S,
    MAX_HARVEST_RECORDS,
    _MULTISPACE_RE,
    RecipeExecutionError,
    find_body_param_path,
    iter_body_params,
    map_records,
    render_field,
    run_recipe,
)
from ..recipe_schema import (
    BROWSER_FETCH,
    BROWSER_FETCH_MAX_PAGES,
    RECIPE_VERSION,
    RECORDS_WILDCARD,
    RecipeError,
    dig,
    dig_records,
    validate_recipe,
)
from ..url_guard import _DNS_EXECUTOR, UrlGuardError, validate_public_url
from .network_capture import CaptureError, CaptureResult, RequestFn, capture_board
from .request_selector import (
    Candidate,
    NoJobsFeedError,
    RequestSelection,
    RequestSelectionError,
    SelectorKeyMissingError,
    derive_url_templates_from_code,
    derive_url_templates_from_links,
    href_templates,
    is_published_url_spec,
    prefilter_candidates,
    published_url_fields,
    repair_url_template,
    select_request,
)

logger = logging.getLogger(__name__)

# The named steps. These strings are the user-visible half of a refusal, so they are
# phrased as what we were DOING, not as an internal module name.
_STEP_ENTRY = "checking the careers URL"
_STEP_CAPTURE = "opening the careers page"
_STEP_FILTER = "finding the jobs feed"
_STEP_SELECT = "reading the jobs feed"
_STEP_SYNTHESIZE = "writing the replay recipe"
_STEP_ACCEPT = "verifying we can read it"

# ...and how those six collapse onto the four DISCOVERY steps the user is shown
# (:mod:`api.services.discovery.progress`). Six exist because six things can fail with
# six different log lines; four are shown because that is how many distinct next
# ACTIONS a person has. The mapping lives here, with the engine, so the UI's vocabulary
# survives the next engine swap exactly the way ``DiscoveryOutcome`` did.
#
# ``_STEP_SELECT`` is deliberately part of "finding the jobs feed": from outside,
# knowing WHICH request serves jobs and knowing how to read its fields are one act.
# Synthesis and acceptance are both "verifying we can read it" — the user cannot act
# differently on "the recipe we assembled is invalid" than on "the replay came back
# with different jobs", and both mean the same thing to them.
_STEP_TO_CHECKLIST: dict[str, str] = {
    _STEP_ENTRY: STEP_OPEN_PAGE,
    _STEP_CAPTURE: STEP_OPEN_PAGE,
    _STEP_FILTER: STEP_FIND_FEED,
    _STEP_SELECT: STEP_FIND_FEED,
    _STEP_SYNTHESIZE: STEP_VERIFY_READ,
    _STEP_ACCEPT: STEP_VERIFY_READ,
}

# Placeholder company id for the acceptance replay only — the real id is minted by the
# service when the outcome is persisted.
_PROBE_COMPANY_ID = "discovery-probe"

# The STORED floor is permissive on purpose (a board must have >= 1 job to be worth
# tracking, and nothing more is knowable today). Guarding the nightly run against a
# shrink is the completeness gate's job — its delta band and 3-run VERIFIED streak —
# not a number frozen at discovery, which would turn every seasonal dip into a FAILED
# run. The ACCEPTANCE floor below is the strict one, because there we have a capture to
# compare against.
_STORED_EXPECTED_MIN_JOBS = 1

# At acceptance, the replay must return at least half of what the capture browser saw
# on its one page. Not equality: a live board legitimately moves between the capture and
# the replay seconds later, and a 50% floor separates "same feed" from "we are reading
# something else".
_ACCEPTANCE_MIN_RATIO = 0.5

# ...and at least this fraction of the capture's ids must reappear in the replay. THE
# match-the-capture check (D5). It is what stops a structurally-perfect recipe pointed
# at the wrong array from being stored.
_MIN_ID_OVERLAP_RATIO = 0.5

# --------------------------------------------------------------------------
# THE TWO PAGE BUDGETS. They answer different questions and were one constant.
# --------------------------------------------------------------------------
# ACCEPTANCE asks "does this recipe read this board from OUR environment?" — which two
# pages answer exactly as well as a hundred, and the whole discovery task is bounded at
# 240s (``discover_custom_company._TASK_TIMEOUT_S``) with a browser capture and an LLM
# call already spent out of it. TWO rather than one because the page-size proof below
# needs a SECOND full page to tell "the board honoured the page size we synthesized"
# apart from "it ignored it and served its own short page".
_ACCEPTANCE_MAX_PAGES = 2

# HARVEST asks "read the WHOLE board", so the stored budget is DERIVED per board from
# its own declared total and the page size we proved (:func:`_harvest_max_pages`).
#
# THERE IS NO FLAT PAGE CEILING ON THAT DERIVATION ANY MORE, and removing it is the
# whole of this change. A flat PAGE ceiling means a different JOB ceiling on every
# board, because the page size belongs to the board: 100 pages was 10,000 jobs of
# amazon.jobs (100/page) and 1,000 jobs of Microsoft's Eightfold board (10/page, hard —
# it ignores ``num``/``limit``/``size``/``pageSize`` alike). Microsoft declares 2,111,
# so we read 47% of it and then labelled it "tracking part of this board" — truncated
# by our own constant and by nothing about Microsoft. The 100 was chosen to fit the leaf
# task's then-120s timeout; the timeout was the thing that was wrong, and it moved
# (``fetch_custom_company._TASK_TIMEOUT_S``).
#
# What bounds a sweep now is what actually costs something, and both live at RUNTIME
# where they can be measured instead of guessed: :data:`recipe_runner.MAX_HARVEST_RECORDS`
# (rows, i.e. memory) and :data:`recipe_runner.HARVEST_TIME_BUDGET_S` (wall clock, i.e.
# the worker slot). The stored budget only has to be big enough to REACH the end of the
# board — over-budgeting costs nothing, because the sweep stops on the first short page.

# THE COVERAGE CLAIM's own bound, and the ONLY place a per-page latency guess is
# allowed. ``_reachable_records`` tells the user how much of their board we can read;
# promising ``page_size * max_pages`` would promise Walmart's whole 47,298 through a
# 10-per-page API — 4,730 sequential pages, ~57 minutes, five times the runtime clock.
# The clock would stop that sweep honestly (cap_hit → UNVERIFIED, closes nothing), but
# the user would already have been told at discovery that we track the whole board. So
# the CLAIM is bounded by what the clock can plausibly read, at the slowest per-page
# cost we have measured on a real board (amazon.jobs ~0.72s; Microsoft ~0.25s) —
# slowest, because the optimistic direction is the one that misleads. The STORED budget
# deliberately does NOT use this number: a latency guess baked into a recipe is a flat
# cap wearing a disguise, and the runtime clock measures rather than guesses.
_MEASURED_SECONDS_PER_PAGE = 0.72
_PAGES_WITHIN_TIME_BUDGET = int(HARVEST_TIME_BUDGET_S / _MEASURED_SECONDS_PER_PAGE)

# Slack on top of ``ceil(declared_total / page_size)``. A board grows between the night
# we discovered it and every night after; with no slack the first new job pushes the
# sweep one page short of the total and the run lands UNVERIFIED forever.
_HARVEST_PAGE_HEADROOM = 2

# THE PAGE SIZE IS A RECIPE PARAMETER, not a property of the board. A careers page asks
# for the page size its own LAYOUT wants (amazon.jobs paints 10 cards), and replaying
# that verbatim is what turned a 22,000-job board into 1,000 sequential requests that
# no nightly budget can hold. Raising it toward this target turns the same board into
# ~100 requests — but ONLY once the board itself has PROVEN it honours the bigger page
# (:func:`_assert_page_size_honoured`). Assuming is the wrong-close: a board that
# silently caps the page at its own size serves a SHORT first page, and a short page is
# precisely how the sweep decides the board ENDED — so an assumed page size reports a
# partial board as a complete one.
_TARGET_PAGE_SIZE = 100

# Parameter names that carry a page size. Matched by SUBSTRING and then CONFIRMED
# against the captured bytes — the parameter's own value must equal the number of
# records the response actually returned. That confirmation is what tells a page-size
# parameter apart from an offset, a radius, or a version number that happens to be
# spelled ``count``.
_PAGE_SIZE_PARAM_HINTS = (
    "limit", "size", "count", "per_page", "perpage", "rows", "take", "results",
)

# How many candidates the acceptance ladder is allowed to work through. Each round costs
# one Haiku call and up to two replays (one of them a Chromium launch), and the whole
# discovery task is bounded at 240s — so this is a real budget, not a formality.
_MAX_SELECTION_ROUNDS = 2

# Keys whose captured value being FALSY marks them as a success sentinel — TikTok's
# ``code: 0``, Amazon's ``error: null``. ``recipe_runner._check_inband_error`` fires on
# TRUTHINESS, so pinning exactly these keys turns a board's own in-band error channel
# into a FAILED run instead of a silently empty harvest. A key whose captured value is
# already truthy (``message: "ok"``) is NOT pinned — it would fail every single run.
_INBAND_ERROR_KEY_CANDIDATES = ("error", "errors", "code", "status", "success")

# --------------------------------------------------------------------------
# THE COVERAGE CHECK — "does the recipe read the board, or a sliver of it?"
# --------------------------------------------------------------------------
# A stored recipe INHERITS THE CAPTURE'S FILTER SCOPE, and that is deliberate: paste a
# careers URL you already narrowed to "Engineering, Remote" and the board is tracked at
# that scope forever, because widening it is a change we cannot validate. That rule is
# right for narrowing THE USER CHOSE. It is wrong for narrowing THE PAGE CHOSE — a
# default tab, a preselected facet, a grouped payload we bound one group of — and the
# three boards below all passed every gate while reading a sliver:
#
#   binance.com    81 of 276 postings — the whole board was in the response, in 14
#                  department groups, and ``records_path`` bound to group 4
#   careers.kakao  8 of 31 — the page fired its own ``part=TECHNOLOGY`` default tab
#   walmart        10 of 47,298 — a chat endpoint that pages 10 at a time
#
# Telling the two apart by INSPECTING THE URL is guesswork. Telling them apart by
# READING THE CAPTURED BYTES is not: a board narrowed by a filter the user asked for
# publishes counts that AGREE with what came back, while a board narrowed by its own
# page publishes counts that contradict it (kakao answers ``totalJobCount: 8`` beside
# its own category counts summing to 31). So the check is: what does the recipe reach,
# against what do the captured bytes prove is there. Detectable, board-agnostic, and it
# needs nothing we did not already download.
#
# The remedy is ordered: WIDEN if we can prove the wider read is the same board
# (:func:`_widen_to_union`), otherwise STOP CLAIMING A CLEAN SUCCESS
# (:data:`OUTCOME_PARTIAL`) — and, below the floor at
# :data:`_COVERAGE_REFUSAL_RATIO`, REFUSE.
#
# NOTE WHAT THIS DOES NOT TOUCH: the oracle, the gate, ``verify_harvest``. A partial
# board keeps exactly the completeness claim it earned, which for all three above is
# one that can never close a job. Coverage is an HONESTY signal, not a safety one — the
# safety is the oracle's job and stays where it is.
_MIN_CAPTURE_COVERAGE = 0.9

# ...and the shortfall must also be worth a word. A board whose own total moved by two
# jobs between the capture and the replay is drift, not a sliver, and labelling it
# "partial" would burn the label on every board that breathes.
_MIN_COVERAGE_SHORTFALL = 5

# THE FLOOR — and the whole of stage S1. Below this fraction of the board's own largest
# published count, the recipe is not "part of the board", it is a different thing that
# happens to live at the same company.
#
# The number was MEASURED, displayed and then drove NOTHING. Walmart's chat endpoint
# reaches 10 records while the very same payload counts 48,800 — ratio 0.0002 — and the
# only thing that happened was a sentence in the checklist saying so. A user reading
# "tracking this board" over 10 of 48,800 jobs has been told something false, and every
# nightly gate downstream agrees with it forever because the baseline was taken on this
# run.
#
# WHY A REFUSAL AND NOT A LOUDER BANNER. The taxonomy's own rule (BIRTH-DEFECTS-PLAN
# §0) is that a REQUIRED thing failing is a refusal and only an optional one degrades.
# "This is the company's job board" is the required claim of the whole feature. Between
# this floor and :data:`_MIN_CAPTURE_COVERAGE` the partial banner still does its job —
# a board we read 60% of is a board worth showing — so the degrade path is untouched
# for every case it was ever right about.
#
# WHY 0.10 AND NOT SOMETHING TIGHTER. It has to clear the honest narrowings the partial
# banner exists for: kakao reaches 8 of 31 (0.26) and binance 81 of 276 (0.29), both of
# which we would rather show than throw away. 0.10 is comfortably below both and
# comfortably above the sliver shapes (Walmart 0.0002). A board whose OWN counts say we
# reach under a tenth of it is not a narrowing, it is the wrong array.
#
# It can only ever fire when the board published a count at all: with no claims,
# ``visible == reachable`` and the ratio is 1.0. Silence costs nothing.
_COVERAGE_REFUSAL_RATIO = 0.10

# Where a board publishes its own total. Searched deterministically (never asked of the
# LLM) because a hallucinated oracle path is a nightly FAILED run, and because this is
# the difference between a board that can ever be VERIFIED and one that is UNVERIFIED
# forever.
_TOTAL_KEY_HINTS = (
    "total", "hits", "count", "numfound", "num_found", "resultcount", "result_count",
    "totalcount", "total_count", "totaljobs", "total_jobs", "totalresults",
)
_MAX_TOTAL_SEARCH_DEPTH = 4

# Request headers never carried into a stored recipe. The exact names are per-connection
# junk or things the runner supplies itself; the SUBSTRING list is the important one — a
# captured session token replays fine TODAY (so acceptance would pass) and starts
# failing the moment it expires, which is a board that looks trackable and silently is
# not. Such a board belongs on the browser_fetch tier, where the browser re-earns its
# credentials same-origin every night, or refused.
_HEADER_DROP_EXACT = frozenset({
    "cookie", "set-cookie", "host", "content-length", "connection", "accept-encoding",
    "authorization", "proxy-authorization", "user-agent", "te", "upgrade", "expect",
})
_HEADER_DROP_SUBSTRINGS = ("token", "auth", "session", "csrf", "xsrf", "signature", "secret")
_HEADER_DROP_PREFIXES = ("sec-", ":")

# --------------------------------------------------------------------------
# NARRATING THE CAPTURE — how often the streaming network log may hit the database
# --------------------------------------------------------------------------
# The capture browser sees a response every few hundred milliseconds during page load,
# and each one is a row the user is watching appear. Publishing per response would turn
# ONE capture into dozens of UPDATEs on the row every open tab is already polling — the
# narration costing more than the thing narrated.
#
# So it is throttled TWICE, because the two bounds fail differently. The INTERVAL is
# tuned to the reader: the list poll runs at 4s (``MyCompaniesList``), so a write more
# often than every ~3s is one nobody can see. The COUNT is the hard bound: the capture
# window is up to 45s of navigation + 24s of settling + a 10s drain, and a purely
# time-based throttle over that is ~26 writes for a board that keeps talking. Twelve
# covers the burst every board fires while its page loads — which is the part worth
# watching — and everything after it rides the step boundaries that were already
# published. Worst case is therefore 12 extra writes per discovery, against the ~5 this
# had before, each one a single ``jsonb_set`` on one row.
_REQUEST_PUBLISH_INTERVAL_S = 3.0
_MAX_REQUEST_PUBLISHES = 12

# One live checklist write, and the live-view URL that reaches it mid-run.
LiveViewFn = Callable[[str], Awaitable[None]]
# ...and the write that takes it back off the row when the browser closes.
LiveViewClosedFn = Callable[[], Awaitable[None]]


class CaptureFn(Protocol):
    """The capture seam — :func:`network_capture.capture_board` or a $0 test double.

    A Protocol rather than a ``Callable`` alias because of the keywords.
    ``on_live_view`` fires the MOMENT a hosted browser session exists, which on the
    Browserbase path is before the page has even been opened. The live view is only
    worth anything while the run is happening, so it cannot ride back on the return
    value — by then the session is released and the iframe would render a dead frame.

    ``on_live_view_closed`` fires when that stops being true, and it is the ONLY
    trustworthy statement of that fact. The browser dies before this function returns;
    step 1 is not ticked over until after the pre-filter has scored the capture and the
    checklist has been published again. Anything downstream that reads "step 1 is still
    active" as "the browser is still open" is reading a signal that is already wrong.
    """

    def __call__(
        self,
        url: str,
        *,
        on_live_view: LiveViewFn | None = None,
        on_live_view_closed: LiveViewClosedFn | None = None,
        on_request: RequestFn | None = None,
    ) -> Awaitable[CaptureResult]: ...


class SelectFn(Protocol):
    """The selection seam — :func:`request_selector.select_request` or a $0 double.

    A Protocol rather than a ``Callable`` alias because of ``feedback``: a second round
    that cannot say WHY the first was rejected is a re-roll of the same question over the
    same bytes, which is the least likely way to get a different answer.
    """

    def __call__(
        self, candidates: list[Candidate], *, feedback: str | None = None
    ) -> Awaitable[RequestSelection]: ...


ReplayFn = Callable[[dict[str, Any]], Awaitable[tuple[list[dict], HarvestEvidence]]]
UrlValidator = Callable[[str], Any]
# One live checklist write. Injected (the task supplies a short-lived DB write), and
# treated as fire-and-forget — see ``_publish`` inside :func:`discover`.
ProgressFn = Callable[[dict[str, Any]], Awaitable[None]]


class _Refusal(Exception):
    """Internal control flow: a named-step refusal. Never escapes :func:`discover`."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


class _PageSizeRefusal(_Refusal):
    """The board did not honour the page size we SYNTHESIZED — retry it as captured.

    A distinct type because the recovery is distinct: every other acceptance refusal
    means this transport cannot read this feed (move to the next tier), while this one
    means only that one derived PARAMETER was wrong, and the same tier replaying the
    board's own observed page size is very likely to work. Without the split, a board
    that caps its page size would be refused outright — the opposite of "detect it at
    acceptance and fall back".
    """


# --------------------------------------------------------------------------
# step 5 — recipe synthesis (pure)
# --------------------------------------------------------------------------

def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _hostname_of(url: str) -> str:
    """Host of ``url``, or ``''``. Display only — the checklist says which page we
    actually landed on, which is how a user spots a redirect to the wrong site."""
    return urlsplit(url).netloc


def _clean_headers(headers: dict[str, str]) -> dict[str, str]:
    """The captured request headers that are safe and useful to replay verbatim.

    Keeps the static, non-secret ones a board genuinely requires — TikTok's
    ``website-path: tiktok`` is exactly this case, and dropping it would make an
    otherwise-deterministic board unreadable. See :data:`_HEADER_DROP_SUBSTRINGS` for
    why the credential-shaped ones are dropped rather than stored.
    """
    out: dict[str, str] = {}
    for raw_name, value in headers.items():
        name = str(raw_name).lower()
        if name in _HEADER_DROP_EXACT:
            continue
        if name.startswith(_HEADER_DROP_PREFIXES):
            continue
        if any(sub in name for sub in _HEADER_DROP_SUBSTRINGS):
            continue
        out[name] = str(value)
    return out


def _post_body(candidate: Candidate) -> dict[str, Any]:
    """The captured POST body as an object, or raise a refusal.

    ``recipe_schema`` requires ``fetch.body`` to be an object because that is what the
    pagination merge writes into. A form-encoded or non-object body is a board this
    vocabulary cannot express, and saying so here is better than storing a recipe whose
    paging silently does nothing.
    """
    try:
        parsed = json.loads(candidate.post_data or "", strict=False)
    except Exception as exc:  # noqa: BLE001
        raise _Refusal(
            _STEP_SYNTHESIZE,
            f"the jobs request POSTs a non-JSON body we cannot replay: {exc}",
        ) from exc
    if not isinstance(parsed, dict):
        raise _Refusal(
            _STEP_SYNTHESIZE,
            "the jobs request POSTs a JSON body that is not an object; "
            "the recipe vocabulary cannot express it",
        )
    return parsed


def _inband_error_keys(payload: Any) -> list[str]:
    """Top-level keys whose CAPTURED value is falsy — the board's success sentinels."""
    if not isinstance(payload, dict):
        return []
    return [k for k in _INBAND_ERROR_KEY_CANDIDATES if k in payload and not payload[k]]


def _find_total_path(payload: Any, records_path: str, record_count: int) -> str | None:
    """The dotted path to the board's own declared total, or ``None``.

    Deterministic breadth-first search over total-ish keys holding an int at least as
    big as the page we captured. Anything inside the records array is skipped: a per-job
    ``count`` is not a board total, and mistaking one for an oracle would make every run
    FAIL its exact-match comparison.

    **Every match is collected and the LARGEST value wins** — never the first one found.
    A board that publishes both a per-page and a whole-board count (``resultCount: 20``
    beside ``totalCount: 500``) lists them in its own order, and taking the first meant
    pinning the PAGE SIZE as the trusted total: the nightly run then harvests page one,
    matches its own "total" exactly, lands VERIFIED ``declared_exact``, and closes every
    job that rolled off page one — on a board it never finished reading (invariant #2).
    The tie always breaks toward the larger number because the two errors are not
    symmetric: too large is UNVERIFIED forever (shows its jobs, closes nothing), too
    small is a confident wrong-close.
    """
    if not isinstance(payload, dict):
        return None
    best: tuple[int, int, str] | None = None      # (value, -depth, path)
    frontier: list[tuple[Any, str, int]] = [(payload, "", 0)]
    while frontier:
        node, path, depth = frontier.pop(0)
        if depth > _MAX_TOTAL_SEARCH_DEPTH or not isinstance(node, dict):
            continue
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if child_path == records_path:
                continue
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= record_count
                and any(hint in str(key).lower() for hint in _TOTAL_KEY_HINTS)
            ):
                found = (value, -depth, child_path)
                if best is None or found > best:
                    best = found
            if isinstance(value, dict):
                frontier.append((value, child_path, depth + 1))
    return best[2] if best is not None else None


def _facet_consensus_total(payload: Any, records_path: str) -> int | None:
    """A whole-board count at least TWO of the board's own facet blocks AGREE on.

    THE CROSS-CHECK ON A DECLARED TOTAL, and the reason it exists is a measured
    wrong-close: amazon.jobs publishes ``hits: 10000`` — not its size, but its
    Elasticsearch WINDOW (``offset + result_limit > 10000`` is a hard in-band error) —
    while six of its facet blocks independently sum to 22,621. A budget derived from
    ``hits`` reads exactly 10,000 rows, matches the "total" exactly, lands VERIFIED
    ``declared_exact`` and closes the other 12,621 live jobs. That is invariant #2
    failing confidently, and it is a failure the OLD flat 10-page budget only avoided
    by never getting anywhere near the total.

    A single facet block is not evidence: one that covers without partitioning
    over-counts (GM's 1,042-vs-835, and amazon's own ``location_facet`` sums to 35,048
    against a real 22,621). AGREEMENT between two independently-computed partitions is,
    and it is the same "believe the corroborated number" rule :func:`_find_total_path`
    already applies when it takes the largest total-ish key.

    Deliberately conservative in its own right: the value is used ONLY to DISTRUST a
    declared total, never to become one. A false positive costs a board its
    ``declared_probed`` oracle (UNVERIFIED forever — shows its jobs, closes nothing);
    a false negative is the wrong-close above.
    """
    if not isinstance(payload, dict):
        return None
    sums: list[int] = []
    frontier: list[tuple[Any, str, int]] = [(payload, "", 0)]
    while frontier:
        node, path, depth = frontier.pop(0)
        if depth > _MAX_TOTAL_SEARCH_DEPTH or not isinstance(node, dict):
            continue
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if child_path == records_path:
                continue
            if isinstance(value, dict):
                frontier.append((value, child_path, depth + 1))
                continue
            # A facet BLOCK: a non-empty list of ``{label: count}`` objects, the exact
            # shape ``recipe_runner.sum_single_valued_facet`` already sums.
            if not isinstance(value, list) or not value:
                continue
            counts: list[int] = []
            for bucket in value:
                if not isinstance(bucket, dict) or not bucket:
                    counts = []
                    break
                for count in bucket.values():
                    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                        counts = []
                        break
                    counts.append(count)
                if not counts:
                    break
            if counts:
                sums.append(sum(counts))
    agreed = [value for value in set(sums) if sums.count(value) >= 2]
    return max(agreed) if agreed else None


def _records_stem(records_path: str) -> str:
    """What the records array CALLS itself, reduced to a matchable stem.

    ``jobs`` → ``job``, ``jobList`` → ``job``, ``data.job_post_list`` → ``jobpost``.
    Used to pick, out of several counts a payload publishes side by side, the one that
    counts THESE records: walmart's response carries ``total_jobs: 47298`` beside
    ``total_future_roles: 276561`` and ``total_content: 36``, and only the first is a
    statement about the array we bound to. Taking the largest instead would report a
    board of 47,298 as a board of 276,561.
    """
    segments = [
        s for s in records_path.split(".")
        if s and s != RECORDS_WILDCARD and not s.isdigit()
    ]
    if not segments:
        return ""
    stem = "".join(ch for ch in segments[-1].lower() if ch.isalnum())
    for suffix in ("list", "s"):
        if len(stem) > len(suffix) + 1 and stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _totals_beside_records(payload: Any, records_path: str, floor: int) -> int | None:
    """The board's own count of THESE records, read from the objects that contain them.

    Scoped to the records array's own container and its dict ANCESTORS, which is where
    a board publishes a total and is not where it publishes anything else: kakao's
    ``jobTypeCountDtoList.2.jobCount`` (14) is a facet bucket two levels down and would
    otherwise be read as a board total, and every payload is full of per-record counts
    shaped exactly like one.

    Deliberately separate from :func:`_find_total_path`, which picks the ORACLE. That
    one may only ever look where a wrong answer is survivable, and its answer decides
    whether a nightly run may close jobs. This one is display-only: it decides whether
    we say "we are reading part of this board", so it can afford to descend a list
    index (walmart buries its total under ``tool_messages.0.artifact``) that the oracle
    search deliberately will not.
    """
    stem = _records_stem(records_path)
    key_of_records = records_path.split(".")[-1] if records_path else ""
    node: Any = payload
    scopes: list[dict[str, Any]] = []
    for segment in [s for s in records_path.split(".") if s]:
        if isinstance(node, dict):
            scopes.append(node)
            if segment not in node:
                break
            node = node[segment]
        elif isinstance(node, list):
            if segment == RECORDS_WILDCARD:
                break
            try:
                node = node[int(segment)]
            except (ValueError, IndexError):
                break
        else:
            break
    if isinstance(node, dict):  # a records_path of "" — the payload IS the array's home
        scopes.append(node)

    named: list[int] = []
    anonymous: list[int] = []
    for scope in scopes:
        for key, value in scope.items():
            if key == key_of_records:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < floor:
                continue
            flat = "".join(ch for ch in str(key).lower() if ch.isalnum())
            if not any(hint.replace("_", "") in flat for hint in _TOTAL_KEY_HINTS):
                continue
            (named if stem and stem in flat else anonymous).append(value)
    # A count that NAMES these records wins outright, however small; only when nothing
    # names them do we fall back to the largest total-ish number in scope.
    pool = named or anonymous
    return max(pool) if pool else None


def _labelled_facet_total(payload: Any, records_path: str) -> int | None:
    """Σ of a ``[{label: "...", count: N}, ...]`` facet block — the board's own tab counts.

    THE KAKAO SIGNAL. Its jobs API answers ``totalJobCount: 8`` for the tab the page
    happened to open, and beside it ships ``jobTypeCountDtoList`` — TECHNOLOGY 8,
    DESIGN 3, BUSINESS_SERVICES 14, STAFF 6. The board is 31 and it says so in the same
    response; the 8 is the scope OUR capture landed in, not the board's size.

    A distinct shape from :func:`_facet_consensus_total`'s ``{label: count}`` buckets,
    and that is exactly what keeps them apart: a bucket carrying a STRING label beside
    ONE integer is a named tab count, while amazon's ``{"US, WA, Seattle": 3409}`` is a
    location histogram that over-counts multi-located jobs (its own ``location_facet``
    sums to 34,794 against a real 22,492). Requiring a string label admits the first and
    excludes the second, so this signal never has to be corroborated the way the other
    one does.

    Used ONLY to say "we are reading part of this board", never as an oracle and never
    as a budget — a false positive costs a truthful-but-pessimistic label, which is the
    survivable direction.
    """
    if not isinstance(payload, dict):
        return None
    best: int | None = None
    frontier: list[tuple[Any, str, int]] = [(payload, "", 0)]
    while frontier:
        node, path, depth = frontier.pop(0)
        if depth > _MAX_TOTAL_SEARCH_DEPTH or not isinstance(node, dict):
            continue
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if child_path == records_path:
                continue
            if isinstance(value, dict):
                frontier.append((value, child_path, depth + 1))
                continue
            if not isinstance(value, list) or len(value) < 2:
                continue
            total = 0
            ok = True
            for bucket in value:
                if not isinstance(bucket, dict):
                    ok = False
                    break
                counts = [
                    v for v in bucket.values()
                    if isinstance(v, int) and not isinstance(v, bool) and v >= 0
                ]
                labels = [v for v in bucket.values() if isinstance(v, str) and v]
                if len(counts) != 1 or not labels:
                    ok = False
                    break
                total += counts[0]
            if ok and total > 0 and (best is None or total > best):
                best = total
    return best


@dataclass(frozen=True)
class _Coverage:
    """What the stored recipe can reach, against what the CAPTURED BYTES prove is there.

    ``evidence`` names where ``visible`` came from, in the board's own vocabulary, so a
    partial verdict is checkable rather than asserted — it is rendered to the user and
    read back off the row months later.
    """

    reachable: int
    visible: int
    evidence: str
    # WHAT THE FEED ITSELF CAN ENUMERATE, with OUR budgets taken back out. ``None``
    # means "the whole array" — a recipe that pages over the board's own list is bounded
    # by nothing the board told us about.
    #
    # THE TWO NUMBERS ANSWER TWO DIFFERENT QUESTIONS and collapsing them refuses boards
    # we read correctly today. ``reachable`` is what the NIGHTLY HARVEST will read, and
    # it is clamped by things that are ours and not the board's: the 600 s clock
    # (:data:`_PAGES_WITHIN_TIME_BUDGET`) and, on the browser tier, 25 pages
    # (:data:`~api.services.recipe_schema.BROWSER_FETCH_MAX_PAGES`). That clamp is
    # exactly what the PARTIAL banner exists to announce.
    #
    # ``feed_reach`` is what the FEED can enumerate, and it is what the refusal floor
    # must be measured against, because the floor's question is "is this array the
    # board, or a sliver of it?" — a question our own page budget has no opinion on.
    # Measured: TikTok publishes 4,026 jobs 10 to a page and replays on the browser
    # tier, so its ``reachable`` is 25 x 10 = 250 — 6% of the board, under any floor
    # worth having, and a board we track perfectly well today at PARTIAL scope. The feed
    # is not a sliver; our page ceiling is.
    feed_reach: int | None = None

    @property
    def is_partial(self) -> bool:
        return (
            self.visible - self.reachable >= _MIN_COVERAGE_SHORTFALL
            and self.reachable < self.visible * _MIN_CAPTURE_COVERAGE
        )

    @property
    def is_refused(self) -> bool:
        """Below :data:`_COVERAGE_REFUSAL_RATIO` of the board's own largest claim.

        Measured on :attr:`feed_reach`, never on :attr:`reachable` — see that field.

        Strictly stronger than :attr:`is_partial` and deliberately NOT and-ed with
        :data:`_MIN_COVERAGE_SHORTFALL`: at this ratio the shortfall is implied — one
        reachable record against a tenth-of-the-board floor already means ``visible``
        is above ten, so the absolute-shortfall guard could never be the thing that
        saves a board here.

        ``visible`` is ``max(claim, reachable)`` by construction, so a board that
        published nothing has ``visible == reachable`` and can never trip this.
        """
        if self.feed_reach is None or self.visible <= 0:
            return False
        return self.feed_reach < self.visible * _COVERAGE_REFUSAL_RATIO

    @property
    def refusal_reason(self) -> str:
        """The user-facing half of :attr:`is_refused`, in the board's own numbers.

        Named as something a person can act on ("this board publishes 48,800 jobs and
        the feed we found returns 10") rather than as a request-shape technicality —
        the pasted URL may simply be a search page or a chat widget, and that is a
        thing the user can fix by pasting a different URL.
        """
        return (
            f"we could only read {self.feed_reach or 0:,} job(s) from the feed we "
            f"found, but {self.evidence} — that is under "
            f"{int(_COVERAGE_REFUSAL_RATIO * 100)}% of the board, so tracking it would "
            "silently miss almost all of it"
        )


def _reachable_records(script: dict[str, Any], candidate: Candidate) -> int:
    """The MOST rows the stored recipe could ever return, at its full nightly budget.

    Not what acceptance read — acceptance is clamped to two pages on purpose
    (:func:`probe_script`) and comparing that against a board's total would call every
    paginated board partial. The claim under test is what the HARVEST can reach.

    ...and the harvest is bounded by a CLOCK, not only by its page budget, so the claim
    is too (:data:`_PAGES_WITHIN_TIME_BUDGET`). Without that second bound a 10-per-page
    board declaring 47,298 jobs (Walmart) derives a 4,732-page budget, "reaches" all of
    it on paper, and is presented to the user as fully tracked — while every nightly run
    stops on the clock at roughly a fifth of it and comes back UNVERIFIED forever. The
    run is safe either way (an unfinished sweep closes nothing); it is the PROMISE that
    would be false, and a false promise here is what the partial banner exists to make.
    """
    for step in script["steps"]:
        if step["op"] in ("paginate_offset", "paginate_page"):
            pages = min(int(step["max_pages"]), _PAGES_WITHIN_TIME_BUDGET)
            budget = int(step["page_size"]) * pages
            window_cap = step.get("window_cap")
            if isinstance(window_cap, int) and window_cap > 0:
                return min(budget, window_cap)
            return budget
    return candidate.record_count


def _feed_reach(script: dict[str, Any], candidate: Candidate) -> int | None:
    """How many rows THE FEED can enumerate, with our own budgets taken back out.

    ``None`` means "as many as the array holds" — a recipe that pages over the board's
    own list is bounded only by the board, and the board told us of no bound. The
    caller reads that as "not a sliver".

    The one board-side bound is ``window_cap``: an API that refuses to serve past
    offset N genuinely cannot enumerate more than N, whatever we ask (amazon.jobs'
    ``hits: 10000`` search window over a real 22,621). That is the board's limit, not
    ours, so it counts.

    A recipe with NO pagination step reaches exactly what the one captured request
    returned, and that number is the whole of :data:`_COVERAGE_REFUSAL_RATIO`'s subject:
    ten rows out of a self-declared 48,800 is not a narrow read of the board, it is a
    different list.
    """
    for step in script["steps"]:
        if step["op"] in ("paginate_offset", "paginate_page"):
            window_cap = step.get("window_cap")
            if isinstance(window_cap, int) and window_cap > 0:
                return window_cap
            return None
    return candidate.record_count


def _coverage(
    script: dict[str, Any], candidate: Candidate, selection: RequestSelection
) -> _Coverage:
    """Measure the stored recipe against the board's own published counts."""
    reachable = _reachable_records(script, candidate)
    feed_reach = _feed_reach(script, candidate)
    payload, records_path = candidate.payload, selection.records_path
    claims: list[tuple[int, str]] = []

    declared = _totals_beside_records(payload, records_path, candidate.record_count)
    if declared is not None:
        claims.append((declared, f"this board's own response counts {declared:,} job(s)"))
    consensus = _facet_consensus_total(payload, records_path)
    if consensus is not None:
        claims.append((consensus, f"this board's own facets agree on {consensus:,} job(s)"))
    labelled = _labelled_facet_total(payload, records_path)
    if labelled is not None:
        claims.append((labelled, f"this board's own category counts add up to {labelled:,}"))

    # The LARGEST claim wins. Each one is a lower bound the board published about
    # itself, so the biggest is the strongest statement that we are short — and the
    # error we care about is missing a sliver, not over-reporting one.
    if not claims:
        return _Coverage(reachable, reachable, "", feed_reach=feed_reach)
    visible, evidence = max(claims)
    return _Coverage(
        reachable, max(visible, reachable), evidence, feed_reach=feed_reach
    )


@dataclass(frozen=True)
class _PageSizeParam:
    """Where a captured request carries the page size it asked for.

    ``path`` is the FULL location inside a POST body and is what the rewrite writes
    to. A one-element path is the flat body every board had until higher.gs.com, whose
    ``pageSize`` sits at ``variables.searchQueryInput.page.pageSize``; scanning only
    ``body.items()`` made that invisible, so ``page_size_attempts`` never tried to
    raise it and the run bought 54 requests where 11 would do. Empty for a query
    parameter, whose name is the whole address.
    """

    location: str      # "query" | "body"
    name: str
    path: tuple[str, ...] = ()


def _apply_page_size(
    fetch: dict[str, Any], candidate: Candidate, page_size: int
) -> int:
    """Rewrite ``fetch`` to ask for ``page_size`` records; return the size it now asks
    for. RAISES a :class:`_Refusal` if the parameter is no longer identifiable.

    The rewrite and the ``paginate.page_size`` must always be the SAME number: the
    sweep reads "fewer records than page_size" as the end of the board, so a recipe
    that asks for 10 and pages by 100 would skip 90 jobs per page, and one that asks
    for 100 and pages by 10 would re-read the same jobs forever.
    """
    param = _page_size_param(candidate)
    if param is None:  # pragma: no cover - the caller only overrides when one exists
        raise _Refusal(
            _STEP_SYNTHESIZE,
            "cannot raise this board's page size: no page-size parameter is "
            "identifiable in the request we captured",
        )
    if param.location == "query":
        fetch["url"] = str(
            httpx.URL(fetch["url"]).copy_set_param(param.name, str(page_size))
        )
    else:
        # WHERE THE BOARD ALREADY CARRIES IT, which for a GraphQL envelope is several
        # levels down. A top-level write would leave the real ``pageSize`` at its
        # captured value while ``paginate.page_size`` claimed the raised one — and a
        # page_size that disagrees with what the request asks for ends the sweep one
        # page early and reports a partial board as a complete one.
        path = param.path or (param.name,)
        node: Any = fetch.setdefault("body", {})
        for segment in path[:-1]:
            node = node[segment]
        node[path[-1]] = page_size
    return page_size


def _is_page_size(name: str, value: Any, record_count: int) -> bool:
    """``name=value`` is the page-size parameter of a response holding ``record_count``.

    Both halves are required. The NAME hint alone matches ``loc_group_id`` and
    ``resultCount``; the VALUE match alone matches an ``offset=10`` on page two. A
    parameter that names a size AND whose captured value is exactly the size we got
    back is the one the board actually paged on.
    """
    if record_count <= 0:
        return False
    if not any(hint in name.lower() for hint in _PAGE_SIZE_PARAM_HINTS):
        return False
    try:
        return int(str(value)) == record_count
    except (TypeError, ValueError):
        return False


def _captured_body(candidate: Candidate) -> dict[str, Any] | None:
    """The captured POST body as a dict, or ``None`` (not a POST / unparseable)."""
    if candidate.method != "POST":
        return None
    try:
        body = json.loads(candidate.post_data or "", strict=False)
    except Exception:  # noqa: BLE001 - a body we cannot parse carries no parameter
        return None
    return body if isinstance(body, dict) else None


def _page_size_param(candidate: Candidate) -> _PageSizeParam | None:
    """The request parameter that set the page we captured, or ``None``. DERIVED from
    the captured request + response, never asked of the model — a guessed page-size
    parameter is a silently-short sweep, which is the wrong-close direction.

    The body scan is NESTED (``iter_body_params``, shallowest first) for the same
    reason the cursor merge is: higher.gs.com carries its page size four levels down a
    GraphQL envelope, and a flat ``body.items()`` scan simply could not see it.
    """
    for name, raw in parse_qsl(urlsplit(candidate.url).query, keep_blank_values=True):
        if _is_page_size(name, raw, candidate.record_count):
            return _PageSizeParam("query", name)
    body = _captured_body(candidate)
    if body is not None:
        for path, name, value in iter_body_params(body):
            if _is_page_size(name, value, candidate.record_count):
                return _PageSizeParam("body", name, path)
    return None


# The only two page numbers a first page can carry, and therefore the only two
# ``start_page`` values discovery will commit to. See :func:`_captured_start_page`.
_STORABLE_START_PAGES = (0, 1)


def _captured_start_page(candidate: Candidate, param: str) -> int | None:
    """The page number the CAPTURED request asked for, when it is a believable base.

    Discovery never emitted this, so ``recipe_runner`` fell back to its default of 1
    while higher.gs.com's captured body says ``pageNumber: 0`` — the sweep skipped the
    board's whole first page. THAT MATTERS BEYOND THE MISSING 20 JOBS: the sweep still
    ends on a short page, so it reports ``terminated_cleanly`` and ``page_advance_ok``,
    and a board with a ``self_consistent`` oracle therefore VERIFIES a read it knows is
    short. Only a VERIFIED run may close a job, so that is a self-inflicted mass close.
    Goldman itself is spared only because its ``declared_probed`` oracle compares at
    tolerance 0 and the count mismatch drops it to UNVERIFIED.

    Only 0 and 1 are storable. Those are the two bases a first page can have; anything
    else means the capture recorded a request from the MIDDLE of a sweep, where the
    board's base is not knowable from one request — and storing "start at page 7" would
    skip six pages every night, which is strictly worse than today's default. That case
    returns ``None`` (unchanged behaviour) and says so in the log.
    """
    raw: Any = None
    for name, value in parse_qsl(urlsplit(candidate.url).query, keep_blank_values=True):
        if name == param:
            raw = value
            break
    if raw is None:
        body = _captured_body(candidate)
        if body is not None:
            path = find_body_param_path(body, param)
            if path is not None:
                node: Any = body
                for segment in path:
                    node = node[segment]
                raw = node
    if raw is None or isinstance(raw, bool):
        return None
    try:
        page = int(str(raw))
    except (TypeError, ValueError):
        return None
    if page not in _STORABLE_START_PAGES:
        logger.info(
            "captured %r=%s is not a first page (expected 0 or 1) — storing no "
            "start_page, so the sweep keeps the runner's default of 1",
            param, page,
        )
        return None
    return page


def _declared_total(candidate: Candidate, selection: RequestSelection) -> int | None:
    """The board's own declared total for this candidate, or ``None``. Pure."""
    total_path = _find_total_path(
        candidate.payload, selection.records_path, candidate.record_count
    )
    if not total_path:
        return None
    try:
        value = dig(candidate.payload, total_path)
    except RecipeError:  # pragma: no cover - _find_total_path only returns live paths
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def page_size_attempts(
    candidate: Candidate, selection: RequestSelection
) -> tuple[int | None, ...]:
    """The page sizes acceptance should try, best first (``None`` = as captured).

    Returns two attempts ONLY for a board where the upgrade is both possible and worth
    a second replay: it pages, it carries a page-size parameter we could identify from
    its own bytes, its captured page is smaller than the target, and its declared total
    says there are at least :data:`_ACCEPTANCE_MAX_PAGES` full target-size pages to
    prove the upgrade against. That last gate is what keeps the fallback replay (a
    second Chromium launch on the browser tier) off every small board — and it is also
    what makes :func:`_assert_page_size_honoured` a sound proof rather than a coin
    flip, since a board with 150 jobs would serve a legitimately short second page.
    """
    if selection.pagination is None:
        return (None,)
    if candidate.record_count >= _TARGET_PAGE_SIZE:
        return (None,)
    if _page_size_param(candidate) is None:
        return (None,)
    declared = _declared_total(candidate, selection)
    if declared is None or declared < _TARGET_PAGE_SIZE * _ACCEPTANCE_MAX_PAGES:
        return (None,)
    return (_TARGET_PAGE_SIZE, None)


def _harvest_max_pages(declared_total: int | None, page_size: int, *, transport: str) -> int:
    """The STORED page budget: ``ceil(total / page_size)`` + slack, under the ceiling.

    Derived from the board's own two numbers, because a flat constant is wrong in both
    directions at once — 10 pages is a 97-job sample of amazon.jobs and 10 wasted
    round-trips on a board with 30 jobs.

    THE CEILING IS EXPRESSED IN JOBS, NOT PAGES, and that is the fix. A flat page
    ceiling silently re-imposes the board's own page size as a job ceiling — 100 pages
    of Microsoft's 10-per-page Eightfold board is 1,000 of its 2,111 jobs. Converting
    :data:`~api.services.recipe_runner.MAX_HARVEST_RECORDS` through the page size we
    PROVED gives every board the same job ceiling regardless of how it paginates.
    ``browser_fetch`` keeps its own, much lower, PAGE ceiling because there the cost is
    per page and not per row — see :data:`~api.services.recipe_schema.BROWSER_FETCH_MAX_PAGES`.

    With NO declared total the derivation has no input, and the only defensible budget
    left is the ceiling itself: the sweep stops on the first short page, so a board
    smaller than the ceiling pays nothing for it, while any smaller flat number would
    truncate exactly the boards whose length we cannot otherwise measure — and a
    ``self_consistent`` board that never reaches its own end is UNVERIFIED forever.
    """
    if page_size <= 0:
        # Defensive: a zero/negative page size would divide by zero below, and a recipe
        # that asks for no rows per page cannot be budgeted at all. One page.
        return 1
    ceiling = (
        BROWSER_FETCH_MAX_PAGES
        if transport == BROWSER_FETCH
        else max(1, MAX_HARVEST_RECORDS // page_size)
    )
    if not isinstance(declared_total, int) or declared_total <= 0:
        return ceiling
    needed = -(-declared_total // page_size) + _HARVEST_PAGE_HEADROOM
    return max(1, min(needed, ceiling))


def probe_script(script: dict[str, Any]) -> dict[str, Any]:
    """The recipe as ACCEPTANCE replays it: identical except the page budget.

    Acceptance must run the PRODUCTION path over the recipe we are about to store —
    that is the whole claim the gate makes — but it must not run the whole HARVEST,
    which is now sized to the board (100 pages of amazon.jobs is ~60s, inside a 240s
    task that has already spent a browser capture and an LLM call). Clamping the one
    field that means "how far", and re-validating, keeps everything acceptance actually
    proves — the URL, headers, body, field map, oracle, in-band error keys and the
    synthesized PAGE SIZE — byte-identical to what gets stored.
    """
    probe: dict[str, Any] = json.loads(json.dumps(script))
    for step in probe["steps"]:
        if step["op"] in ("paginate_offset", "paginate_page"):
            step["max_pages"] = min(step["max_pages"], _ACCEPTANCE_MAX_PAGES)
    # validate-on-write applies to the probe too: a clamp that produced an invalid
    # recipe would be replayed as one, and the refusal would name the wrong thing.
    validate_recipe(
        probe, transport=probe["transport"], oracle_kind=probe["oracle"]["kind"]
    )
    return probe


def synthesize_recipe(
    candidate: Candidate,
    selection: RequestSelection,
    *,
    transport: str,
    origin_url: str,
    page_size_override: int | None = None,
) -> dict[str, Any]:
    """Assemble a validated replay recipe from one candidate + the model's mapping.

    Everything here except the field map and the paging hint is DERIVED from the bytes
    we captured, not asked of the model: the oracle, the in-band error keys, the headers
    and the body all come from the real request/response. That is deliberate — those are
    the parts where a plausible hallucination costs a nightly FAILED run rather than a
    refusal we would see immediately.

    ``page_size_override`` is the one parameter this function does NOT derive on its
    own: raising the board's page size is a claim only the acceptance replay can settle
    (see :func:`page_size_attempts`), so the caller decides which size to build and the
    gate decides whether it was true. ``None`` reproduces the captured page exactly.

    RAISES :class:`_Refusal` (never a bare ``RecipeError``) so the caller's reason names
    the step the user is shown.
    """
    fetch: dict[str, Any] = {
        "op": "fetch",
        "method": candidate.method,
        "url": candidate.url,
        "headers": _clean_headers(candidate.request_headers),
    }
    if candidate.method == "POST":
        fetch["body"] = _post_body(candidate)

    steps: list[dict[str, Any]] = [fetch]

    total_path = _find_total_path(
        candidate.payload, selection.records_path, candidate.record_count
    )
    declared_total = dig(candidate.payload, total_path) if total_path else None
    # IS THE DECLARED TOTAL THE BOARD'S SIZE, OR ITS SEARCH WINDOW? See
    # :func:`_facet_consensus_total` — amazon.jobs' ``hits: 10000`` is a window whose
    # real board is 22,621, and trusting it as an oracle closes 12,621 live jobs the
    # moment the budget below is big enough to reach it. When the board's own facets
    # contradict its total we keep the number (it is still the furthest offset the API
    # will serve, so it makes a correct ``window_cap``) and refuse to make it the
    # completeness ORACLE.
    consensus_total = _facet_consensus_total(candidate.payload, selection.records_path)
    total_is_capped = (
        isinstance(declared_total, int)
        and consensus_total is not None
        and consensus_total > declared_total
    )
    if total_is_capped:
        logger.info(
            "discovery distrusts declared total %s at %r — the board's own facets agree "
            "on %s; storing it as a window_cap, not an oracle",
            declared_total, total_path, consensus_total,
        )

    page_size = candidate.record_count
    if page_size_override is not None:
        page_size = _apply_page_size(fetch, candidate, page_size_override)

    # PAGE WHENEVER WE HAVE A USABLE HINT. The single exception is a board whose own
    # total PROVES the captured page is the whole board — there a second request would
    # buy an empty page every night. Gating on "a total exists AND says there is more"
    # was the bug: a board that paginates but publishes no total lost its paging step
    # silently, and a page-1-only sweep reports ``terminated_cleanly`` with no cap, so
    # ``self_consistent`` VERIFIES it night after night and starts closing everything
    # past page one (invariant #2). Note the oracle below refuses to certify a
    # page-1-only recipe for exactly the residual case — no total AND no hint.
    one_page_proven = (
        isinstance(declared_total, int)
        and declared_total <= candidate.record_count
        and not total_is_capped
    )
    if selection.pagination is not None and not one_page_proven:
        op = "paginate_offset" if selection.pagination.style == "offset" else "paginate_page"
        paginate: dict[str, Any] = {
            "op": op,
            "param": selection.pagination.param,
            # The page size the recipe ACTUALLY ASKS FOR — the captured one unless the
            # caller is testing an upgrade, in which case ``fetch`` was rewritten to
            # request it. Never the model's guess: a page_size that disagrees with what
            # the request asks for terminates the sweep one page early ("short page")
            # and reports a partial board as a complete one.
            "page_size": page_size,
            # DERIVED from this board's own total and page size, not a flat constant —
            # the harvest has to be able to reach the end of the board, or the
            # completeness gate can never answer anything but UNVERIFIED.
            "max_pages": _harvest_max_pages(
                declared_total if isinstance(declared_total, int) else None,
                page_size,
                transport=transport,
            ),
        }
        if op == "paginate_page":
            # THE BASE THE BOARD COUNTS FROM, read off its own captured request. The
            # runner defaults to 1 and higher.gs.com starts at 0, so omitting this
            # skipped the board's entire first page — see :func:`_captured_start_page`
            # for why a short-but-clean sweep is the dangerous shape of that bug.
            start_page = _captured_start_page(candidate, selection.pagination.param)
            if start_page is not None:
                paginate["start_page"] = start_page
        if total_is_capped and isinstance(declared_total, int):
            # The furthest the API will serve. Without it the sweep walks past the
            # window and the board answers with an in-band error — a FAILED run every
            # night instead of an honest ``cap_hit`` → UNVERIFIED.
            paginate["window_cap"] = declared_total
        steps.append(paginate)

    steps.append({
        "op": "extract_json_path",
        "records_path": selection.records_path,
        "fields": dict(selection.field_map),
    })

    # THE POSTING DATE (POSTED-DATE-PLAN.md §5/U6). ``parse_date`` has been fully
    # implemented in the runner since Phase 3a and was never emitted here, so every
    # discovered board stored its date exactly as the board spelled it and the leaf
    # task then failed to read it — 2,217 of 2,217 Microsoft rows with a NULL
    # ``posted_on`` while the payload carried ``postedTs: 1787617881`` on every one.
    #
    # No step for ISO (already the shape the leaf task reads) and no step when the
    # format is unrecognized: §3's rule is that a value we cannot turn into a date is
    # not a date, so it stays NULL and ``first_seen_at`` falls back to first sight.
    # Emitting a `humanized` step for "unrecognized" would claim we identified a
    # relative string when we did not; the outcome is identical and the claim is not.
    posted_at_format = selection.posted_at_format
    if (
        "posted_at" in selection.field_map
        and posted_at_format is not None
        and posted_at_format.mode != "iso"
    ):
        parse_date: dict[str, Any] = {
            "op": "parse_date",
            "field": "posted_at",
            "mode": posted_at_format.mode,
        }
        if posted_at_format.format is not None:
            parse_date["format"] = posted_at_format.format
        steps.append(parse_date)

    error_keys = _inband_error_keys(candidate.payload)
    if error_keys:
        steps.append({"op": "assert_no_inband_error", "error_keys": error_keys})
    steps.append({"op": "dedupe_key", "field": "id"})
    steps.append({"op": "assert_unique", "field": "id"})

    # THE COMPLETENESS CLAIM, and the one place discovery may not be generous.
    # ``self_consistent`` means "the sweep ran to a short page without hitting its cap"
    # — a claim a recipe with NO sweep has not earned. A single request that returns
    # page one of an unknown-length board is indistinguishable from one that returns
    # the whole board, so a page-1-only recipe with no declared total gets ``none``:
    # ``verify_harvest`` can then only ever answer UNVERIFIED, which shows the board's
    # jobs every night and closes none of them. That is the safe half of the ambiguity.
    paginates = any(step["op"].startswith("paginate_") for step in steps)
    oracle: dict[str, Any]
    if total_path and not total_is_capped:
        oracle = {"kind": "declared_probed", "total_path": total_path}
    elif paginates:
        oracle = {"kind": "self_consistent"}
    else:
        oracle = {"kind": "none"}

    script: dict[str, Any] = {
        "script_version": RECIPE_VERSION,
        "transport": transport,
        "expected_min_jobs": _STORED_EXPECTED_MIN_JOBS,
        # Resolves leading-slash hrefs the board returns relative (Amazon's ``job_path``)
        # against the origin the capture actually landed on.
        "base_url": _origin_of(origin_url),
        "steps": steps,
        "oracle": oracle,
        # Stamped BEFORE the validation below, never after. ``validate_recipe`` runs
        # again on every nightly READ, so a key added post-validation would store a
        # recipe that passes once here and then fails every replay forever.
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "discovered_by": f"capture/{transport}",
    }
    if transport == "browser_fetch":
        script["origin_url"] = origin_url

    try:
        validate_recipe(script, transport=transport, oracle_kind=oracle["kind"])
    except RecipeError as exc:
        raise _Refusal(_STEP_SYNTHESIZE, f"the recipe we assembled is invalid: {exc}") from exc

    # THE WALMART CATCH, and the cheapest probe in the whole ladder: does the request we
    # are about to store SAY it read one page?
    #
    # ``page_shape_refusal`` is checks 13a/13b of the nightly gate, already written,
    # already pure — and discovery never called it. So a recipe whose fetch carries
    # ``job_page=1`` with no step advancing it passed synthesis, passed acceptance (the
    # replay reads back the SAME ten rows the browser saw, so the match-the-capture check
    # is delighted) and was stored. Measured on careers.walmart.com: 10 jobs tracked out
    # of 48,800. Every later gate agrees with it forever, because the baseline it is
    # measured against was taken on this run.
    #
    # THE ONE EXCEPTION IS EVIDENCE BEATING SHAPE. When the board's own declared total
    # says the captured page IS the whole board, a page index in the request means "page
    # one is all of it" and refusing would throw away boards we read correctly today.
    # ``one_page_proven`` is exactly that statement and nothing weaker — a total that the
    # board's own facets contradict (``total_is_capped``) does not count.
    if not one_page_proven:
        shape = page_shape_refusal(script, candidate.record_count)
        if shape is not None:
            raise _Refusal(
                _STEP_SYNTHESIZE,
                "this board's own request asks for one page of results and we could not "
                f"work out how to ask for the next one ({shape}) — tracking it would "
                f"show {candidate.record_count} job(s) and silently miss the rest",
            )
    return script


# --------------------------------------------------------------------------
# step 6 — the acceptance gate
# --------------------------------------------------------------------------

async def _default_replay_http(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
    """Tier 1a acceptance: the EXACT production replay path — ``run_recipe`` over the
    SSRF-guarded sync client, in a thread so the blocking DNS/sockets never stall the
    worker's loop."""
    def _run() -> tuple[list[dict], HarvestEvidence]:
        http = guarded_sync_client()
        try:
            return run_recipe(
                script, http,
                transport=script["transport"], oracle_kind=script["oracle"]["kind"],
            )
        finally:
            http.close()

    return await asyncio.to_thread(_run)


async def _default_replay_browser(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
    """Tier 1b acceptance: the EXACT production replay path for ``browser_fetch`` — a
    FRESH local Chromium via the same subprocess the nightly harvest uses. Imported
    lazily so this module's import graph never even references the browser_fetch parent
    until a board actually needs the tier."""
    from ..browser_fetch.runner import run_browser_fetch

    return await run_browser_fetch(
        script, transport=script["transport"], oracle_kind=script["oracle"]["kind"]
    )


def _rebind_to_selection(candidate: Candidate, selection: RequestSelection) -> Candidate:
    """Re-point the candidate at the array the MODEL chose, not the pre-filter's guess.

    The pre-filter picks one array per response by ``(job_score, record_count)`` — a
    deliberately dumb ranking — and the prompt explicitly invites the model to correct
    it ("use the one you were shown unless it is wrong"). Everything downstream reads
    the candidate: :func:`_capture_ids` compares the replay against ``candidate.records``,
    ``paginate.page_size`` and :func:`_find_total_path`'s floor come from
    ``candidate.record_count``. Left un-rebound, an accepted correction makes those read
    a DIFFERENT array than the recipe extracts — measured: a 12-job ``job_list`` beside
    a 30-row ``saved_searches`` decoy refused a perfectly readable board with "the
    replay returned 12 job(s) but the browser saw 30", a message that is also simply
    false, and wrote 30 as the page size of a 12-record page.

    ``select_request`` already proved the path resolves; the guard is for an injected
    selector (tests) and for a future caller that does not.
    """
    try:
        records = dig_records(candidate.payload, selection.records_path)
    except RecipeError as exc:
        raise _Refusal(
            _STEP_SELECT,
            f"records_path {selection.records_path!r} does not resolve in the "
            f"captured response: {exc}",
        ) from exc
    if not isinstance(records, list) or not records:
        raise _Refusal(
            _STEP_SELECT,
            f"records_path {selection.records_path!r} is not a non-empty list in the "
            "captured response",
        )
    if selection.records_path == candidate.records_path:
        return candidate
    return replace(
        candidate, records_path=selection.records_path, record_count=len(records)
    )


def _union_records_path(records_path: str) -> str | None:
    """``4.postings`` → ``*.postings``: the same array in EVERY group, or ``None``."""
    segments = records_path.split(".")
    for i, segment in enumerate(segments):
        if segment.isdigit() and i < len(segments) - 1:
            return ".".join(segments[:i] + [RECORDS_WILDCARD] + segments[i + 1:])
    return None


def _widen_to_union(
    candidate: Candidate, selection: RequestSelection, base_url: str
) -> tuple[Candidate, RequestSelection]:
    """Re-point a path that bound ONE GROUP of a grouped payload at the whole board.

    THE BINANCE FIX, and the reason it is deterministic code rather than a better
    prompt: binance.com answers with 14 department groups, the pre-filter ranked
    ``4.postings`` top because 88 was the biggest single group, and the model — shown
    that path and asked to correct it only "if it is wrong" — agreed. Every downstream
    check then passed, because every one of them compares the replay against that same
    88-record array. Nothing in the pipeline could see the other 188 postings sitting in
    the response we had already downloaded. The prompt now names the ``*`` path too, but
    a prompt is a request; this is the guarantee.

    Widening is PROVEN, not assumed, and the proof is the only one that matters: the
    union must map to strictly MORE usable job rows through the same field map. That
    rules out the two ways this could go wrong — a wildcard over groups whose arrays
    hold something other than jobs (they would not render an id and a title), and a
    wildcard that resolves to the same records under another name. The acceptance replay
    then re-proves the whole thing against the live board.

    A widened selection is still the SAME REQUEST at the SAME filter scope. Nothing here
    edits a URL, drops a query parameter or changes what the browser asked for — it only
    stops throwing away part of the answer we already had.
    """
    union_path = _union_records_path(selection.records_path)
    if union_path is None:
        return candidate, selection
    try:
        union = dig_records(candidate.payload, union_path)
    except RecipeError:
        return candidate, selection
    if not isinstance(union, list) or len(union) <= candidate.record_count:
        return candidate, selection
    field_map = dict(selection.field_map)
    widened_rows = map_records(union, field_map, base_url)
    if len(widened_rows) <= len(map_records(candidate.records, field_map, base_url)):
        # The extra groups carry no job we can actually write. Keeping the narrow path
        # is the honest outcome — the coverage check below still tells the user we are
        # only reading part of the board.
        return candidate, selection
    logger.info(
        "discovery widened records_path %r -> %r: %d -> %d record(s) from the SAME "
        "captured response",
        selection.records_path, union_path, candidate.record_count, len(union),
    )
    return (
        replace(candidate, records_path=union_path, record_count=len(union)),
        replace(selection, records_path=union_path),
    )


def _repair_selection_url(
    selection: RequestSelection, candidate: Candidate, captured: CaptureResult
) -> RequestSelection:
    """``selection`` with a dead url template re-pointed at the board's real route key.

    The evidence is THE CAPTURE'S OWN REQUEST LOG — every URL the browser fetched on
    the board's host while the page was open, which on a Next.js board includes the
    ``/_next/data/<build>/roles/<id>.json`` call each job card makes. That is where the
    board itself spells its route key, so nothing has to be guessed or re-fetched.
    :func:`~.request_selector.repair_url_template` owns the rule and refuses unless it
    is certain; this only supplies the two inputs it cannot reach.
    """
    board_host = urlsplit(_origin_of(captured.final_url) or captured.final_url).hostname or ""
    repaired = repair_url_template(
        candidate.records,
        selection.field_map["url"],
        [response.url for response in captured.responses],
        board_host,
    )
    if repaired == selection.field_map["url"]:
        return selection
    return replace(selection, field_map={**selection.field_map, "url": repaired})


# --------------------------------------------------------------------------
# step 5b — PROVING the job link, when we are the one who invented it
# --------------------------------------------------------------------------
#
# WHY THIS STEP EXISTS. ``field_map.url`` is either a link the BOARD published or a
# path WE invented with an id pasted into it, and until this existed both were stored
# on the strength of looking like a URL. Measured over 19 real payloads
# (docs/implementations/custom-company-sources/JOB-LINK-RULE.md): 13 boards publish a
# link field, 6 force a template, and THREE of those six shipped a dead link —
# Jane Street a flat 404, Goldman and Walmart a 200 that serves the same empty SPA
# shell for every job. Nothing in the pipeline could see any of it.
#
# THE SPLIT IS THE RULE. A published path is the board's own statement and is never
# fetched, re-pointed or second-guessed; a synthesised one is a claim of ours and has
# to be PROVED before it is stored. The line between them is
# ``request_selector.is_published_url_spec``.
#
# WHY A PUBLISHED LINK MUST NOT BE PROBED, even though probing looks free: the proof
# below CANNOT tell a client-rendered job page from a client-rendered 404 shell, and
# plenty of published links point at exactly that. Measured over the 13 published links
# in the corpus, 11 would pass a probe and TWO working production links would not:
# Atlassian's iCIMS page renders the job in an IFRAME, so three different jobs each
# serve 18,086 chars and none carries its title — the same shape as Goldman's dead
# shell; and Roblox's page carries a related-jobs block, so every page holds the other
# jobs' titles too and the pages differ by 0.8%. Atlassian is also the board this change
# was told not to regress.

# The proof's budget. At most two candidate specs, two jobs each — four GETs per
# selection round, on the ~1 board in 3 that needs a template at all; ten of the
# thirteen corpus boards fetch nothing.
#
# THE WORST CASE HAS TO FIT THE TASK'S CLOCK. ``discover_custom_company`` wraps the
# whole run in a 240 s ``asyncio.timeout``, and discovery already spends 27–75 s in a
# real browser. Two rounds x two candidates x two jobs, every one of them timing out,
# is 8 x 10 s = 80 s — inside the remaining headroom, and only reachable on a board
# that is refusing to answer us at all.
_LINK_PROBE_SAMPLES = 2
_LINK_PROBE_TIMEOUT_S = 10.0
# A job page is HTML, not a download. Matches the capture's own per-body cap for the
# same reason it was raised to 4 MB — real pages get that big.
#
# TRUNCATION CANNOT MANUFACTURE A PASS, which is why there is no guard for it. Reading
# stops on the first chunk past the cap, so two clipped bodies land within one chunk
# (~64 KB) of each other on length alone — comfortably inside the 2% bar below, which
# is 80 KB at this cap. A clipped pair that still differs differs because their first
# 4 MB genuinely differ, and that IS the routing evidence the proof is looking for.
# The error truncation can cause is the safe one: two pages that diverge only after
# 4 MB read as identical, and an identical pair is REFUSED.
_LINK_PROBE_MAX_BYTES = 4_000_000
# How different two job pages must be before "different" means anything. Both bounds
# are needed: the fraction alone calls a 400-char difference in a 500-char shell
# decisive, and the absolute alone calls a 250-char nonce in a 700 KB SPA decisive.
_MIN_PAGE_DELTA_CHARS = 200
_MIN_PAGE_DELTA_FRACTION = 0.02

# One probe fetch: ``url -> (status, body)``. A status of 0 means the fetch never
# happened (guard refusal, DNS, timeout, reset) and is treated exactly like a 500 —
# unproven, never fatal.
ProbeFn = Callable[[str], tuple[int, str]]

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>")
_TAG_RE = re.compile(r"<[^>]+>")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "‐": "-", "‑": "-", "‒": "-", "–": "-",
                         "—": "-", "―": "-"})


def _default_probe(url: str) -> tuple[int, str]:
    """GET ``url`` through the SAME SSRF-guarded client the nightly replay uses.

    Never raises: every failure is ``(0, "")``, because "we could not check" and "the
    check failed" lead to the same place — the link is unproven and will not be stored.
    Reusing ``guarded_sync_client`` is not incidental; this fetches a URL a model
    composed, which is the exact threat that client's host-pin and IP-pin exist for.
    """
    try:
        http = guarded_sync_client()
    except Exception:                       # pragma: no cover - client build cannot fail
        return 0, ""
    try:
        with http.stream("GET", url, timeout=_LINK_PROBE_TIMEOUT_S) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) >= _LINK_PROBE_MAX_BYTES:
                    break
            return response.status_code, bytes(body).decode("utf-8", "replace")
    except Exception as exc:                # noqa: BLE001 - every failure is "unproven"
        logger.info("job-link probe could not fetch %s: %r", url, exc)
        return 0, ""
    finally:
        http.close()


def _page_text(body: str) -> str:
    """An HTML body reduced to comparable words.

    Scripts and styles go first and for a reason bigger than noise: an SPA's payload
    lives in a ``<script>`` tag, so a shell that renders nothing can still carry every
    job's title in its bundle. Stripping them is what makes "the page is about THIS
    job" mean the page, not the app.
    """
    text = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", body))
    text = unicodedata.normalize("NFKD", html.unescape(text)).translate(_QUOTES)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _MULTISPACE_RE.sub(" ", text).strip().casefold()


def _pages_differ(first: str, second: str) -> bool:
    """The two pages are materially different lengths — i.e. the URL routed on the id."""
    if not first or not second:
        return False
    longest = max(len(first), len(second))
    return abs(len(first) - len(second)) >= max(
        _MIN_PAGE_DELTA_CHARS, int(_MIN_PAGE_DELTA_FRACTION * longest)
    )


# How long a job title has to be before finding it on a page means anything. "QA" or
# "SRE" occurs on half the web by accident, which would turn the proof's strongest
# signal into its weakest. Below the bar the title is simply not consulted — it is not
# a reason to reject the board.
_DISTINCTIVE_TITLE_CHARS = 10


def _link_samples(
    records: list[Any], field_map: dict[str, str], base_url: str
) -> list[tuple[str, str]]:
    """``(normalized title, absolute url)`` for :data:`_LINK_PROBE_SAMPLES` jobs with
    DISTINCT urls, or fewer if the board cannot supply them.

    Distinct on the URL and nothing else, because that is the only thing the proof
    requires: two records that render the same url prove nothing about routing. Titles
    may repeat (the same role in two cities is two jobs), and a repeated or too-short
    title costs only the title half of the proof — :func:`_prove_job_link` falls back to
    comparing the pages themselves.
    """
    picked: list[tuple[str, str]] = []
    urls: set[str] = set()
    for record in records:
        rendered = render_field(record, field_map["url"])
        if not isinstance(rendered, str):
            continue
        url = base_url.rstrip("/") + rendered if rendered.startswith("/") else rendered
        if not url.startswith(("https://", "http://")) or url in urls:
            continue
        title = render_field(record, field_map["title"])
        urls.add(url)
        picked.append((_page_text(title) if isinstance(title, str) else "", url))
        if len(picked) == _LINK_PROBE_SAMPLES:
            break
    return picked


def _prove_job_link(
    records: list[Any], field_map: dict[str, str], base_url: str, probe: ProbeFn
) -> str | None:
    """``None`` if this url spec is proved, else WHY it is not. Sync; never raises.

    THE PROOF, and why it is two REAL jobs rather than one job plus a fabricated
    control id. An HTTP status decides nothing — ``higher.gs.com/roles/<anything>``
    answers 200, and so does every path on ``careers.walmart.com``. Fetching a
    deliberately-bogus id as a control would work, but the id has to be INVENTED, and
    an invented id can collide with a real posting and quietly prove the opposite.

    Two real jobs need no invention and answer a sharper question: **if the board
    serves the same page for two different jobs, the template does not route on this
    id.** Measured 2026-08-29, after :func:`_page_text` — Goldman's wrong key 23 vs 23
    chars, its right one 4,003 vs 3,383 with each title on its own page; Walmart 1,606
    vs 1,606; Kakao 60 vs 60; Jane Street a 404 before the comparison is even reached.

    Each page carrying its OWN title and not the other's is the strong form, and the
    "not the other's" half is what stops a board that answers every job URL with its
    full listing page from passing. When the titles are too short to be distinctive or
    the two jobs share one, only the weak form is available and that is fine — a board
    that serves two different pages IS routing on the id, whatever is written on them.
    """
    samples = _link_samples(records, field_map, base_url)
    if len(samples) < _LINK_PROBE_SAMPLES:
        return f"only {len(samples)} of the board's jobs render a distinct link"

    pages: list[tuple[str, str]] = []
    for title, url in samples:
        status, body = probe(url)
        if status == 0 or status >= 400:
            return f"HTTP {status} on {url}"
        pages.append((title, _page_text(body)))

    (first_title, first_page), (second_title, second_page) = pages
    if (
        first_title != second_title
        and min(len(first_title), len(second_title)) >= _DISTINCTIVE_TITLE_CHARS
    ):
        own = first_title in first_page and second_title in second_page
        cross = first_title in second_page or second_title in first_page
        if own and not cross:
            return None
    if _pages_differ(first_page, second_page):
        return None
    return (
        f"two different jobs served the same page ({len(first_page)} vs "
        f"{len(second_page)} chars) — this link does not point at one job"
    )


# A dotted path no payload can carry (``dig`` splits on ``.``, so no key can be named
# this). ``render_field`` substitutes an unresolvable path with the empty string, which
# is how the fallback stays a TEMPLATE — and therefore renders at all — when the id spec
# cannot be interpolated into one.
_UNRESOLVABLE_PATH = "__no_job_id__"


def _board_page_link(origin_url: str, id_spec: str) -> str:
    """The honest last resort: the board's OWN listing page, keyed by the job id.

    NOT a per-job link and not pretending to be one. It is the page the user pasted, it
    cannot 404, and clicking it lands on the list the job is actually on — which is
    strictly better than the alternatives. ``url`` is one of
    ``CANONICAL_REQUIRED_FIELDS``, so "store nothing" is not available, and an empty
    one reaches the frontend as ``href=""`` (which reloads the page: worse than a 404
    and no more honest). Refusing the board outright would throw away a feed we can
    read perfectly — Jane Street's 233 jobs and its whole hiring-trend graph — to
    protect a footnote.

    The id rides in the FRAGMENT: it keeps one row per job distinct, and a fragment is
    never sent to the server, so it cannot turn a working listing URL into a 404.

    An id path that itself contains a brace would nest inside that placeholder and
    render a mangled string on every row, so it gets a placeholder that resolves to
    nothing instead. That still has to BE a placeholder: ``render_field`` reads a spec
    with no ``{`` as a dotted PATH, so a bare literal URL renders ``None`` on every
    row — the empty link this whole function exists to avoid.
    """
    page = origin_url.split("#", 1)[0]
    if "{" in id_spec or "}" in id_spec:
        return f"{page}#{{{_UNRESOLVABLE_PATH}}}"
    return f"{page}#{{{id_spec}}}"


# --------------------------------------------------------------------------
# step 5c — DERIVING a job link, when the board never published one
# --------------------------------------------------------------------------
#
# THE CEILING ``_prove_job_link`` COULD NOT RAISE. That proof is verification-only: it
# can show a template is wrong and it cannot find the right one, so a board with no
# published link field fell all the way to :func:`_board_page_link` — a
# ``listing-page#{id}`` fragment that is honest and is not a job link. Measured on Jane
# Street: 233 jobs, every one linking to the same page.
#
# The derivations live in ``request_selector`` (they are pure and belong with the other
# url rules); what lives HERE is the only part that touches the network — reading the
# board's own scripts when its rendered page carries no job anchors at all.

# The whole job-link ladder's wall clock, ACROSS selection rounds. Each proof is two
# GETs and each script is one, and while every one of them is a fetch of the board's own
# host — which the capture just proved answers us — an arrangement of timeouts must not
# be able to eat the discovery task's 240s. This is the hard stop; everything below it
# is a preference.
_LINK_RESOLUTION_BUDGET_S = 75.0
# How many of the board's own scripts we are willing to read, once per discovery. This
# is the LAST-RESORT source and it is consulted only when the page publishes no link
# field and renders no job anchors — roughly the one board in six that has nothing else
# to offer. Measured on Jane Street: 2 same-host scripts, 394 KB, 28 ms of body reads,
# so in the normal case this number is not the binding constraint. It is five rather
# than two because a bundler splits a board's code into chunks and the one that builds
# the job list is not reliably the first; the shared DEADLINE above, not this count, is
# what bounds the pathological case.
_MAX_SCRIPT_FETCHES = 5
# How many candidate specs are put through the two-real-jobs proof per round.
_MAX_PROVE_ATTEMPTS = 4


class _JobLinkContext:
    """State the job-link ladder must keep BETWEEN selection rounds.

    The one thing that genuinely has to survive is the script read: it is the only part
    of the ladder that costs network before a candidate exists, and a second round
    re-fetching the same bundles would double the bill for bytes that cannot have
    changed. The deadline is shared for the same reason — a per-call budget multiplied by
    the round count is not a budget.
    """

    def __init__(self, captured: CaptureResult, probe: ProbeFn) -> None:
        self.captured = captured
        self.probe = probe
        self.deadline = time.monotonic() + _LINK_RESOLUTION_BUDGET_S
        self._code_templates: list[str] | None = None

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline

    async def code_templates(self) -> list[str]:
        """``href="…${…}…"`` literals from the board's OWN scripts. Fetched once, ever.

        WHY THIS SOURCE EXISTS AT ALL. Jane Street's careers page is a chooser: it fetches
        all 233 roles as JSON and renders NONE of them, so there are no anchors to mine —
        measured 2026-08-30, its rendered DOM contains zero job ids. The script it loads
        contains the answer verbatim::

            `<a href="/join-jane-street/position/${t.id}/">`

        Through the SAME SSRF-guarded ``ProbeFn`` seam the link proof uses, because it is
        the same threat: a URL that came off a page a stranger pasted. Everything it
        returns is still only a CANDIDATE — the bundle also builds ``/search/?query={}``,
        which the proof rejects for serving the same page to two different jobs.
        """
        if self._code_templates is not None:
            return self._code_templates
        self._code_templates = []
        board_host = _hostname_of(self.captured.final_url)
        base = _origin_of(self.captured.final_url)
        fetched = 0
        for src in self.captured.board_scripts:
            if fetched >= _MAX_SCRIPT_FETCHES or self.expired():
                break
            url = src if src.startswith(("http://", "https://")) else urljoin(base, src)
            if _hostname_of(url) != board_host:
                continue                     # somebody else's CDN is not this board's code
            fetched += 1
            status, body = await asyncio.to_thread(self.probe, url)
            if status == 0 or status >= 400 or not body:
                continue
            for template in href_templates(body):
                if template not in self._code_templates:
                    self._code_templates.append(template)
        logger.info(
            "read %d of the board's own script(s) for a link template; found %d",
            fetched, len(self._code_templates),
        )
        return self._code_templates


async def _derived_candidates(
    selection: RequestSelection,
    candidate: Candidate,
    context: _JobLinkContext,
    origin_url: str,
) -> list[str]:
    """Job-url templates DERIVED from the board's own evidence, best first.

    Anchors first and code second, because an anchor is a link the board actually
    rendered while a code template is one it says it builds. The second source is only
    consulted when the first found nothing, so a board that links its own jobs never
    pays for a script fetch.
    """
    records = candidate.records
    base_url = _origin_of(origin_url)
    board_host = _hostname_of(origin_url)
    id_spec = selection.field_map.get("id")
    derived = derive_url_templates_from_links(
        records, list(context.captured.board_links), base_url, board_host, id_spec=id_spec,
    )
    if derived:
        return derived
    return derive_url_templates_from_code(
        records,
        await context.code_templates(),
        base_url,
        board_host,
        id_spec=id_spec,
        careers_path=urlsplit(origin_url).path,
    )


async def _resolve_job_link(
    selection: RequestSelection,
    candidate: Candidate,
    context: _JobLinkContext,
    origin_url: str,
) -> tuple[RequestSelection, bool, str]:
    """``(selection with a url we can stand behind, is it a per-job link, why not)``.

    The ladder, in the order the evidence deserves:

    1. **the board published this path** — keep it verbatim, fetch nothing. Microsoft's
       ``https://apply.careers.microsoft.com{positionUrl}`` and Atlassian's
       ``portalJobPost.portalUrl`` both land here and are byte-identical afterwards.
    2. **the board published a path and the model invented one instead** — take the
       board's. It answers the question the model was guessing at.
    3. **a template is unavoidable** — build every candidate the board's own evidence
       supports and PROVE each by fetching two real jobs, best first: derived from the
       page's anchors, then from the board's own code, then ``repair_url_template``'s
       swap (it only fires when the model's id appears in ZERO of the board's links,
       which is evidence in its own right), then the model's own answer.
    4. **nothing proved** — :func:`_board_page_link`, and say so out loud.

    Rung 3 is the new one, and the split it rests on is that DERIVING and TRUSTING are
    different acts. Every candidate — ours or the model's — goes through the same proof,
    so a derivation that is wrong is rejected by the same gate that rejects a guess.

    NEVER raises. An unprovable link is a downgrade, never a refusal: refusing would
    throw away a feed we can read perfectly to protect a footnote.
    """
    records = candidate.records
    base_url = _origin_of(origin_url)
    spec = selection.field_map["url"]

    def _with(new_spec: str) -> RequestSelection:
        return replace(selection, field_map={**selection.field_map, "url": new_spec})

    if is_published_url_spec(records, spec):
        return selection, True, ""

    published = published_url_fields(records)
    if published:
        logger.warning(
            "field_map.url %r is a path we invented, but this board publishes its own "
            "link at %r — using the board's", spec, published[0],
        )
        return _with(published[0]), True, ""

    derived = await _derived_candidates(selection, candidate, context, origin_url)
    repaired = _repair_selection_url(selection, candidate, context.captured).field_map["url"]

    tried: list[str] = []
    why = ""
    for attempt in [*derived, repaired, spec]:
        if attempt in tried:
            continue
        if len(tried) >= _MAX_PROVE_ATTEMPTS or context.expired():
            logger.warning(
                "job-link proof budget spent after %d attempt(s) on %s", len(tried), origin_url
            )
            break
        tried.append(attempt)
        unproven: str | None = await asyncio.to_thread(
            _prove_job_link, records, {**selection.field_map, "url": attempt},
            base_url, context.probe,
        )
        why = unproven or ""
        if not why:
            logger.info("job link %r proved against the live board", attempt)
            return _with(attempt), True, ""
        logger.warning("job link %r is not usable: %s", attempt, why)

    fallback = _board_page_link(origin_url, selection.field_map["id"])
    logger.warning(
        "no per-job link could be proved for %s (tried %s); linking every job at this "
        "board to its own listing page instead (%r)", origin_url, tried, fallback,
    )
    return (
        _with(fallback),
        False,
        f"field_map.url {spec!r} is not a link to one job: {why or 'unproven'}",
    )


def _capture_ids(candidate: Candidate, selection: RequestSelection, base_url: str) -> set[str]:
    """The ids the CAPTURE BROWSER saw, mapped with the same field map the recipe uses.

    Same ``map_records`` the replay goes through, on purpose: comparing ids derived two
    different ways would compare the mappers, not the feeds. ``candidate`` must already
    be rebound by :func:`_rebind_to_selection`, or this reads the wrong array.
    """
    rows = map_records(candidate.records, dict(selection.field_map), base_url)
    return {row["id"] for row in rows}


def _assert_matches_capture(
    rows: list[dict], candidate: Candidate, selection: RequestSelection, base_url: str
) -> None:
    """THE match-the-capture assertion (D5). Raises :class:`_Refusal` on a mismatch."""
    expected = _capture_ids(candidate, selection, base_url)
    if not expected:
        raise _Refusal(
            _STEP_ACCEPT,
            "the captured response yielded no usable job ids to compare against",
        )
    floor = max(1, int(len(expected) * _ACCEPTANCE_MIN_RATIO))
    if len(rows) < floor:
        raise _Refusal(
            _STEP_ACCEPT,
            f"the replay returned {len(rows)} job(s) but the browser saw "
            f"{len(expected)} — too few to believe it is the same feed",
        )
    replayed = {str(row["id"]) for row in rows}
    overlap = len(expected & replayed)
    if overlap < max(1, int(len(expected) * _MIN_ID_OVERLAP_RATIO)):
        raise _Refusal(
            _STEP_ACCEPT,
            f"only {overlap} of the {len(expected)} job(s) the browser saw came back "
            "from the replay — we are not reading the same list",
        )


def _assert_page_size_honoured(evidence: HarvestEvidence, page_size: int) -> None:
    """PROVE the board served the page size the recipe asked for. Raises
    :class:`_PageSizeRefusal`.

    THE CHECK THAT MAKES A SYNTHESIZED PAGE SIZE SAFE. A board that ignores or caps the
    parameter answers a 100-record request with its own 10 records, and the sweep reads
    that short page as "the board ended" — so the harvest would report 10 jobs as a
    COMPLETE board and, on a ``self_consistent`` oracle, VERIFY it and close the rest.
    Detecting it here is the difference between a derived parameter and a guessed one.

    The evidence is read exactly: a probe budget of :data:`_ACCEPTANCE_MAX_PAGES` that
    ran out (``terminated_cleanly`` False means the sweep did NOT stop on a short page)
    having fetched every page it was allowed is the same statement as "both pages came
    back full at the size we asked for". ``page_size_attempts`` only offers the upgrade
    when the declared total says that many full pages exist, so a short page here is
    the board disagreeing with us, never the board simply being small.
    """
    if evidence.pages_fetched < _ACCEPTANCE_MAX_PAGES or evidence.terminated_cleanly:
        raise _PageSizeRefusal(
            _STEP_ACCEPT,
            f"this board does not serve {page_size} records per page — it returned a "
            f"short page after {evidence.pages_fetched} page(s), which a sweep would "
            "read as the end of the board",
        )


async def _try_acceptance(
    script: dict[str, Any],
    candidate: Candidate,
    selection: RequestSelection,
    *,
    replay: ReplayFn,
    prove_page_size: int | None = None,
) -> list[dict]:
    """Replay ``script`` from the production path and assert it read the right board.

    ``run_recipe`` / ``run_browser_fetch`` already enforce 2xx, JSON, the in-band error
    keys, a resolving records path, non-empty, the ``expected_min_jobs`` floor and the
    oracle — the RAISES-never-empty ladder, reused rather than reimplemented. On top of
    that this runs the SAME structural gate the nightly harvest runs (so a board that
    could never pass the gate is refused now rather than discovered and then broken every
    night), and finally the match-the-capture check.

    ``prove_page_size`` is set when the recipe asked for a page size the board did not
    choose for itself; it is checked FIRST because it is the most specific diagnosis
    available — every later check would pass on a short page and blame the wrong thing.
    """
    rows, evidence = await replay(script)
    if prove_page_size is not None:
        _assert_page_size_honoured(evidence, prove_page_size)
    jobs = recipe_rows_to_job_listings(_PROBE_COMPANY_ID, rows)
    gate = run_gate(jobs, evidence, oracle_kind=script["oracle"]["kind"])
    if gate.is_zero or not gate.jobs:
        raise HarvestGateError("the replay produced no usable job rows")
    _assert_matches_capture(rows, candidate, selection, script.get("base_url", ""))
    return rows


# --------------------------------------------------------------------------
# the orchestrator
# --------------------------------------------------------------------------

async def _public_candidates(
    candidates: list[Candidate], validate: UrlValidator
) -> list[Candidate]:
    """Drop every candidate whose endpoint fails the SSRF guard (invariant #4, the
    discovered-endpoint half).

    Ordering matters: the shape pre-filter runs FIRST so this pays for DNS only on the
    handful of job-shaped survivors, and it runs BEFORE the LLM sees anything so a page
    that XHRs an internal address can never get that address into a prompt, let alone
    into a stored recipe.
    """
    loop = asyncio.get_running_loop()
    kept: list[Candidate] = []
    for candidate in candidates:
        try:
            await loop.run_in_executor(_DNS_EXECUTOR, validate, candidate.url)
        except UrlGuardError as exc:
            logger.info("discovery dropped non-public endpoint %s: %s", candidate.url, exc)
            continue
        kept.append(candidate)
    # Re-index so ``chosen_request_index`` still means "position in the list you saw".
    return [replace(candidate, index=i) for i, candidate in enumerate(kept)]


def _selection_feedback(
    detail: str | None, selection: RequestSelection | None, link_why: str = ""
) -> str:
    """Everything we MEASURED about the last answer, as a prompt block.

    Three sources, and each says something the others cannot:

    * ``detail`` — the refusal that ended the round. This is the only one that names
      what actually stopped us.
    * ``selection.field_notes`` — the optionals the field-quality prune deleted. A drop
      is a DEGRADE and never causes a round of its own, so these ride along for free
      whenever a round happens anyway; there is no other moment the model can be told
      that ``locations[0].city`` renders nothing on every record of this board.
    * ``link_why`` — the job-link probe's verdict, when it got as far as fetching. It
      never causes a round either (an unprovable link degrades to the board's listing
      page), but it is the sharpest evidence we ever hold about a url the model wrote.

    Deduplicated and ordered, because the same detail can arrive from two of them.
    """
    lines: list[str] = []
    for line in (detail, link_why, *(selection.field_notes if selection else ())):
        if line and line not in lines:
            lines.append(line)
    return "\n".join(f"- {line}" for line in lines)


async def discover(
    url: str,
    *,
    capture: CaptureFn | None = None,
    select: SelectFn | None = None,
    replay_http: ReplayFn | None = None,
    replay_browser: ReplayFn | None = None,
    validate_url: UrlValidator | None = None,
    probe_link: ProbeFn | None = None,
    emit: ProgressFn | None = None,
) -> DiscoveryOutcome:
    """Run one capture discovery for ``url``. NEVER raises — a failure is a REFUSE.

    Every collaborator is an injectable keyword-only seam defaulting to the real thing,
    so the unit tests exercise the whole ladder at $0 with no browser, no LLM and no
    network — the same discipline ``run_browser_fetch`` and the retired browser-agent
    discover used.

    ``emit`` receives the checklist as the run advances, so the user watches named
    steps land instead of a spinner. The TERMINAL checklist is NOT emitted — it
    rides back on ``DiscoveryOutcome.progress`` so the persist writes it in the same
    statement that flips the row (see that field's docstring).
    """
    # The URL seam is ``url_guard.validate_public_url`` itself — raising
    # ``UrlGuardError``, whose reason codes are an API contract. The step naming is done
    # HERE rather than inside a wrapper so an injected validator (tests) takes exactly
    # the same paths as the real one.
    check_url = validate_url or validate_public_url
    probe_job_link = probe_link or _default_probe
    do_capture = capture or capture_board
    do_select = select or select_request
    run_http = replay_http or _default_replay_http
    run_browser = replay_browser or _default_replay_browser

    ledger = ProgressLedger()

    async def _publish() -> None:
        """Push one live checklist update — and NEVER let it decide the outcome.

        A progress write is cosmetic; the discovery is not. An exception escaping this
        seam would land in the broad handler at the bottom and REFUSE a board we can
        perfectly well read, because the database hiccuped while we were narrating —
        the exact inversion of what this feature is for.
        """
        if emit is None:
            return
        try:
            await emit(ledger.snapshot())
        except Exception:  # noqa: BLE001
            logger.warning(
                "discovery progress write failed for %s (continuing)", url, exc_info=True
            )

    async def _publish_live_view(live_view_url: str) -> None:
        """Put the hosted live view on the row WHILE step 1 is still running.

        This is the entire reason the capture seam takes a callback. Written from here
        the blob reaches the poller with ``open_page`` still ``active``, which is the
        only window in which a user can actually watch the session; the terminal write
        below carries the same URL only so the record is complete.
        """
        ledger.set_live_view_url(live_view_url)
        await _publish()

    async def _publish_live_view_closed() -> None:
        """Take the hosted live view back OFF the row the moment it stops being one.

        The capture seam fires this from the ``finally`` that releases the session, so
        it lands while ``open_page`` is still ``active`` — there is a whole pre-filter,
        an LLM call and a replay between the browser closing and step 1 ticking over.
        That gap is the bug this exists to close: the frontend used to infer liveness
        from the step state and kept the iframe mounted over a socket Browserbase had
        already hung up on ("Debugging connection was closed"). Now liveness is a FACT
        the blob carries, not something the UI derives from a step that means something
        else.

        Deliberately NOT routed through the request throttle: this is a state change
        with no later write guaranteed to repeat it, and a dropped one is a dead iframe
        that stays on screen for the rest of the run. ``_publish`` is unconditional;
        only :func:`_publish_request` throttles, and only because every one of its
        writes is superseded by the next.
        """
        ledger.set_live_view_url(None)
        await _publish()

    # Throttle state for the streaming network log. Plain locals + ``nonlocal`` rather
    # than a dict, so mypy sees a float and an int and not ``dict[str, object]``.
    last_request_publish = 0.0
    request_publishes = 0

    async def _publish_request(record: dict[str, Any]) -> None:
        """Record ONE response the capture browser just saw, and maybe say so.

        The ledger always gets the row — accumulating is free and the terminal write
        would carry it anyway. What is throttled is the DATABASE, on the two bounds at
        :data:`_REQUEST_PUBLISH_INTERVAL_S` / :data:`_MAX_REQUEST_PUBLISHES`.

        Dropping a publish is not dropping the row: the very next publish carries every
        row accumulated since, because the ledger renders the WHOLE log on every write.
        That is what makes throttling safe here and would not be true of an event
        stream — a poll that lands mid-capture always sees a complete, self-consistent
        list, which is the same property the checklist itself is built on.
        """
        nonlocal last_request_publish, request_publishes
        ledger.note_request(
            method=record.get("method"),
            url=record.get("url"),
            status=record.get("status"),
            size_bytes=record.get("bytes"),
            truncated=bool(record.get("truncated")),
        )
        now = time.monotonic()
        if request_publishes >= _MAX_REQUEST_PUBLISHES:
            return
        if now - last_request_publish < _REQUEST_PUBLISH_INTERVAL_S:
            return
        last_request_publish = now
        request_publishes += 1
        await _publish()

    attempts = 0
    # The step we are CURRENTLY in, so the last-resort handler at the bottom names the
    # step that actually blew up. Initialized before the try because an exception can
    # be raised from the very first line inside it.
    current_step = _STEP_ENTRY
    try:
        ledger.start(STEP_OPEN_PAGE)
        await _publish()

        # STEP 1 — SSRF on the pasted URL, off the loop (blocking getaddrinfo on a host
        # a stranger chose; see network_capture for the whole argument).
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(_DNS_EXECUTOR, check_url, url)
        except UrlGuardError as exc:
            raise _Refusal(
                _STEP_ENTRY, f"blocked by our safety check ({exc.reason}): {exc}"
            ) from exc

        # STEP 2 — one browser session, ever.
        current_step = _STEP_CAPTURE
        try:
            captured = await do_capture(
                url,
                on_live_view=_publish_live_view,
                on_live_view_closed=_publish_live_view_closed,
                on_request=_publish_request,
            )
        except CaptureError as exc:
            raise _Refusal(_STEP_CAPTURE, str(exc)) from exc

        # ``captured.live_view_url`` IS DELIBERATELY NOT COPIED BACK ONTO THE LEDGER
        # HERE. It used to be, as a belt-and-braces "in case the callback never fired",
        # and that copy is precisely how a retracted live view came back from the dead:
        # the capture seam clears the URL from inside the ``finally`` that closes the
        # browser, and this line — three statements later, before the very next publish
        # — put the now-dead URL straight back on the row. The URL on the result is a
        # record of which session ran, not a claim that it is still watchable; every
        # session that ever had one published it through ``_publish_live_view`` while it
        # was live, which is the only moment the value is true.
        # THE CAPTURE IS THE AUTHORITY, so the streamed log is thrown away and rebuilt
        # from it. The two can legitimately differ: the child announces a response the
        # moment it records one, and the parent then DROPS report entries it cannot
        # fully believe (``_responses_from_report`` skips a malformed row rather than
        # failing the capture). The list the user is reading has to be the same list the
        # pre-filter is about to score, or every record count below would land one row
        # out — so this rebuilds rather than trying to reconcile two lists by position.
        ledger.reset_requests()
        for response in captured.responses:
            ledger.note_request(
                method=response.method,
                url=response.url,
                status=response.status,
                # ``body_bytes`` and not ``len(body)``: an oversize body is carried back
                # EMPTY, and reporting the board's biggest response as 0 bytes is the
                # precise opposite of the evidence an oversize refusal needs.
                size_bytes=response.body_bytes or len(response.body),
                truncated=response.truncated,
            )
        ledger.finish(
            STEP_OPEN_PAGE,
            f"opened {_hostname_of(captured.final_url) or url} — recorded "
            f"{len(captured.responses)} JSON request(s)",
        )
        ledger.start(STEP_FIND_FEED)
        await _publish()

        # The origin a browser_fetch recipe navigates to, and the base for relative
        # hrefs. Falls back to the pasted URL when the capture ended somewhere we may
        # not store (validate_recipe requires https).
        origin_url = (
            captured.final_url
            if captured.final_url.startswith("https://") else url
        )

        # STEP 3 — deterministic pre-filter, then the endpoint SSRF half.
        current_step = _STEP_FILTER
        candidates = prefilter_candidates(captured.responses)
        # THE PRE-FILTER'S VERDICT ON EVERY ROW, published before any refusal below can
        # leave the function. The commonest refusal we serve is "none of the 14 JSON
        # requests this page made returned a list of job postings", and that sentence is
        # an assertion with no evidence unless the fourteen rows are sitting under it
        # saying 0 records each.
        scores = {c.source_index: c.record_count for c in candidates}
        ledger.score_requests(scores)
        if not candidates:
            # Three genuinely different boards, and the user's next action differs, so
            # the copy does too: a page that fetched NO JSON at all is server-rendered
            # or bot-walled (measured: metacareers.com captures zero XHRs); a page
            # whose jobs feed was too big to record whole is a size limit on OUR side,
            # not a property of the board; and a page that fetched plenty of readable
            # JSON with no jobs in it usually means the jobs live behind a
            # filter/search the capture never triggered.
            #
            # The middle case has to be named separately or it is a lie: an oversize
            # body is dropped by the pre-filter's ``json.loads``, and folding that into
            # "none of them returned a list of job postings" tells the user the exact
            # opposite of what happened and leaves them nothing to do.
            oversize = sum(1 for r in captured.responses if r.truncated)
            if not captured.responses:
                detail = (
                    "this page loaded its jobs without any JSON request we could "
                    "record — it renders them on the server or blocks automated "
                    "browsers"
                )
            elif oversize:
                detail = (
                    f"{oversize} of the {len(captured.responses)} JSON request(s) this "
                    "page made returned more data than we can record in one go, and "
                    "none of the rest is a list of job postings"
                )
            else:
                detail = (
                    f"none of the {len(captured.responses)} JSON request(s) this page "
                    "made returned a list of job postings"
                )
            raise _Refusal(_STEP_FILTER, detail)
        public = await _public_candidates(candidates, check_url)
        blocked = set(scores) - {c.source_index for c in public}
        if blocked:
            # Re-marked rather than marked once, because "job-shaped but at an address
            # we refuse to fetch" is a different row state from "no jobs in it" and it
            # is only knowable after the SSRF re-check.
            ledger.score_requests(scores, blocked=blocked)
        candidates = public
        if not candidates:
            raise _Refusal(
                _STEP_FILTER,
                "the only job-shaped requests this page made point at addresses we "
                "refuse to fetch",
            )
        # The count the checklist reports for step 2, pinned BEFORE the round loop
        # starts eating candidates — "found 1 candidate feed" on round two would be
        # narrating our own retry, not what we found on this page.
        feed_count = len(candidates)

        # STEPS 4-6 — ask, synthesize, prove. Each round burns ONE Haiku call and at
        # most two replays; a failed candidate is removed and the next round asks again
        # over what is left, which is how "try the next candidate" stays a real
        # fallback instead of reusing a field map that belonged to a different feed.
        # The step + detail of the most recent failure. Carried as a PAIR because the
        # final refusal must name the step that actually failed: "writing the replay
        # recipe" and "verifying we can read it" are different problems with different
        # next actions for the user, and collapsing both into the last step would tell
        # them the wrong one.
        last_step = _STEP_ACCEPT
        last_error: str | None = None
        # WHAT WE MEASURED ABOUT THE LAST ANSWER, carried into the next ask. Until this
        # existed a second round re-rolled the same question over the same bytes, which
        # is the least likely way to get a different answer — and on a SINGLE-FEED board
        # there was no second round at all, because the loop dropped the failed candidate
        # and found nothing left to ask about. That is exactly the case that needs one:
        # Jane Street and Atlassian each publish ONE jobs feed.
        feedback: str | None = None
        # Did we end up with a link to the JOB, or only to the board? Set every round
        # by :func:`_resolve_job_link`; initialised here because a round that refuses
        # before reaching it still falls through to the checklist below.
        per_job_link = True
        # ...and WHY not, when it is not. Empty on the happy path; carried into the next
        # round's feedback so the model learns what the probe learned.
        link_why = ""
        # The job-link ladder's shared state — one deadline and one script read for the
        # WHOLE discovery, not one per round. See :class:`_JobLinkContext`.
        link_context = _JobLinkContext(captured, probe_job_link)
        for round_number in range(1, _MAX_SELECTION_ROUNDS + 1):
            if not candidates:
                break
            attempts = round_number
            current_step = _STEP_SELECT
            try:
                selection = await do_select(candidates, feedback=feedback)
            except NoJobsFeedError as exc:
                # The model looked at what is left and said none of it is jobs. Asking
                # again cannot change that, and the alternative — a schema with no
                # refusal branch — is what lets a leftover filter catalogue be stored
                # as the company's board. Stop here and name the FILTER step, because
                # that is the user's real problem: we recorded requests, none is a
                # jobs feed.
                logger.info("discovery found no jobs feed for %s: %s", url, exc)
                raise _Refusal(
                    _STEP_FILTER,
                    f"none of the {len(captured.responses)} JSON request(s) this page "
                    "made is a list of job postings",
                ) from exc
            except SelectorKeyMissingError as exc:
                # Not the board's fault and not retryable: refuse WITHOUT counting an
                # attempt, exactly as the location cascade degrades on a missing key.
                logger.warning("discovery cannot run: %s", exc)
                ledger.fail(
                    STEP_FIND_FEED, "discovery is not configured on this deployment"
                )
                return DiscoveryOutcome(
                    ok=False,
                    refuse_reason=f"{_STEP_SELECT}: discovery is not configured on this deployment",
                    attempts=0,
                    progress=ledger.snapshot(outcome=OUTCOME_REFUSED),
                )
            except RequestSelectionError as exc:
                # A rejected answer costs this ROUND, not the whole discovery: the model
                # is being asked to read a truncated sample, and a second ask over the
                # same candidates is cheap next to refusing a board we can read. It is
                # bounded by _MAX_SELECTION_ROUNDS like every other round.
                last_step, last_error = _STEP_SELECT, str(exc)
                feedback = str(exc)
                logger.info("discovery selection rejected for %s: %s", url, exc)
                continue

            ledger.finish(STEP_FIND_FEED, f"found {feed_count} candidate feed(s)")
            ledger.start(STEP_VERIFY_READ)
            await _publish()

            current_step = _STEP_SYNTHESIZE
            try:
                candidate = _rebind_to_selection(
                    candidates[selection.chosen_request_index], selection
                )
                # ...and if that bound ONE GROUP of a grouped payload, take the whole
                # board instead. Before the acceptance ladder, because everything it
                # measures — the page size, the ids to match, the coverage verdict —
                # must be about the array we are actually going to store.
                candidate, selection = _widen_to_union(
                    candidate, selection, _origin_of(origin_url)
                )
                # ...and then settle the job link. After the widen so it reads the
                # final record array, and before synthesis so the stored recipe and
                # the acceptance replay carry the same link. A published link is kept
                # untouched; one WE invented is DERIVED from the board's own evidence,
                # fetched and proved, or downgraded to the board's own listing page.
                # See :func:`_resolve_job_link`.
                selection, per_job_link, link_why = await _resolve_job_link(
                    selection, candidate, link_context, origin_url
                )
            except _Refusal as exc:
                last_step, last_error = exc.step, exc.detail
                feedback = _selection_feedback(exc.detail, selection)
                logger.info("discovery selection unusable for %s: %s", url, exc.detail)
                continue
            # The page sizes to try, best first. ``None`` means "exactly what the
            # capture asked for" and is ALWAYS the last attempt, so a board that
            # refuses a bigger page falls back to the recipe we know works rather than
            # being refused for a parameter we chose.
            attempts_ps = page_size_attempts(candidate, selection)
            accepted: tuple[str, dict[str, Any], list[dict]] | None = None
            for transport, replay in (("http_json", run_http), ("browser_fetch", run_browser)):
                for page_size_override in attempts_ps:
                    try:
                        script = synthesize_recipe(
                            candidate, selection, transport=transport,
                            origin_url=origin_url,
                            page_size_override=page_size_override,
                        )
                        current_step = _STEP_ACCEPT
                        # THE STORED recipe carries the whole-board budget; ACCEPTANCE
                        # replays the same recipe with only that budget clamped. Two
                        # budgets, one recipe — see ``probe_script``.
                        rows = await _try_acceptance(
                            probe_script(script), candidate, selection, replay=replay,
                            prove_page_size=page_size_override,
                        )
                    except _Refusal as exc:
                        last_step, last_error = exc.step, exc.detail
                        logger.info(
                            "discovery %s rejected for %s on %s (page_size=%s): %s",
                            transport, url, candidate.url, page_size_override,
                            exc.detail,
                        )
                        # A page-size refusal costs this ATTEMPT; every other refusal
                        # is about the FEED and the next page size cannot fix it.
                        if isinstance(exc, _PageSizeRefusal):
                            continue
                        break
                    except (
                        RecipeExecutionError, RecipeError, HarvestGateError, ValueError,
                        # A TRANSPORT failure costs this TIER, not the discovery. httpx
                        # raises ConnectTimeout/ConnectError/RemoteProtocolError — none
                        # of them a RecipeExecutionError — on exactly the boards tier 1b
                        # exists for (a bot-walled origin that RSTs or blackholes a
                        # non-browser client). Uncaught, they escaped BOTH loops into the
                        # last-resort handler and permanently refused a board browser_fetch
                        # would have accepted. ``OSError`` covers the same class out of the
                        # browser_fetch subprocess spawn.
                        httpx.HTTPError, OSError,
                    ) as exc:
                        last_step = _STEP_ACCEPT
                        last_error = f"{type(exc).__name__}: {exc}"
                        logger.info(
                            "discovery %s replay failed for %s on %s (page_size=%s): %s",
                            transport, url, candidate.url, page_size_override, last_error,
                        )
                        # A board that REJECTS the bigger page (amazon.jobs answers
                        # "Result limit cannot be greater than 100" in-band, i.e. a
                        # RecipeExecutionError, not a short page) must fall back to the
                        # captured size, not be refused for a parameter we invented.
                        if page_size_override is not None:
                            continue
                        break

                    accepted = (transport, script, rows)
                    break
                if accepted is not None:
                    break

            # THE LAST QUESTION, and the one nothing above can answer: we proved we can
            # read this feed — is this feed the board? Measured against the board's own
            # published counts, in the bytes we already captured.
            #
            # It runs BEFORE the accept block rather than inside it because below
            # :data:`_COVERAGE_REFUSAL_RATIO` the answer is "no", and "no" has to be able
            # to cost this CANDIDATE rather than the discovery: a page that fires a chat
            # widget and a real jobs feed should end up storing the second one. Dropping
            # ``accepted`` here is what puts us on the next-candidate path below.
            coverage: _Coverage | None = None
            if accepted is not None:
                coverage = _coverage(accepted[1], candidate, selection)
                if coverage.is_refused:
                    last_step, last_error = _STEP_ACCEPT, coverage.refusal_reason
                    logger.warning(
                        "capture discovery REFUSED a replayable candidate for %s: %s %s "
                        "reaches %s record(s) against a published %d (records_path=%r)",
                        url, candidate.method, candidate.url, coverage.feed_reach,
                        coverage.visible, selection.records_path,
                    )
                    accepted = None

            if accepted is not None:
                assert coverage is not None  # set in lockstep with ``accepted`` above
                transport, script, rows = accepted
                (paginate_step,) = (
                    [s for s in script["steps"] if s["op"].startswith("paginate_")]
                    or [{}]
                )
                logger.info(
                    "capture discovery ACCEPTED %s: %s %s -> %d jobs on a %d-page probe "
                    "(transport=%s oracle=%s round=%d harvest_budget=%sx%s "
                    "coverage=%d/%d%s)",
                    url, candidate.method, candidate.url, len(rows),
                    _ACCEPTANCE_MAX_PAGES, transport, script["oracle"]["kind"],
                    round_number, paginate_step.get("max_pages"),
                    paginate_step.get("page_size"),
                    coverage.reachable, coverage.visible,
                    " PARTIAL" if coverage.is_partial else "",
                )
                if coverage.is_partial:
                    logger.warning(
                        "capture discovery accepted %s at PARTIAL scope: the recipe "
                        "reaches %d record(s) but %s (records_path=%r)",
                        url, coverage.reachable, coverage.evidence,
                        selection.records_path,
                    )
                # MARK THE WINNER IN THE NETWORK LOG, with the bytes behind it. This is
                # the answer to "which one did you pick, and what did it say?" — and it
                # is only written HERE, after the acceptance replay, so "chosen" can
                # never mean "the model liked the look of it".
                #
                # The sample is one record FROM THE CAPTURE, not from the replay rows:
                # the rows are already mapped into our own {title, location, url} shape
                # (that is what ``job_preview`` shows), and the question this answers is
                # what the BOARD sent. ``payload_sample`` clips and redacts it — a
                # captured record can be tens of kilobytes of HTML description and can
                # echo a session token back in its own JSON.
                captured_records = candidate.records
                ledger.choose_request(
                    candidate.source_index,
                    note=(
                        f"{len(rows)} job(s) came back when we replayed it "
                        + ("in a browser" if transport == "browser_fetch"
                           else "from our own servers")
                    ),
                    records_path=candidate.records_path,
                    records=len(captured_records),
                    sample=payload_sample(
                        captured_records[0] if captured_records else None
                    ),
                )
                # The step's result is the honest one either way. A board we can only
                # read a slice of must not tick the same tick as one we read whole —
                # that identical green tick is the bug this whole check exists for.
                #
                # ...and the same argument for the LINK: a board whose per-job link we
                # could not prove must not report the same tick as one whose links we
                # fetched and stood behind. Appended rather than substituted so the
                # partial-scope sentence keeps its exact wording.
                read_note = (
                    f"read {len(rows)} job(s), but {coverage.evidence} — we can only "
                    f"track part of this board"
                    if coverage.is_partial
                    else f"read {len(rows)} job(s)"
                )
                if not per_job_link:
                    read_note += (
                        " — this board publishes no link to its individual jobs and we "
                        "could not work one out, so every job links to the board's own "
                        "listing page"
                    )
                ledger.finish(STEP_VERIFY_READ, read_note)
                ledger.finish(
                    STEP_READY,
                    "reading part of the board — every job we can see, refreshed daily"
                    if coverage.is_partial
                    else "reading the board's own feed directly — no browser needed"
                    if transport == "http_json"
                    else "reading the board in a browser each night",
                )
                # THE RUNG THIS RUN DOES NOT OWN. The caller enqueues the first harvest
                # the moment it persists this outcome, and that harvest is what puts
                # jobs on the row — so the checklist opens the rung here and the harvest
                # task closes it (``progress.with_first_scan``). Leaving the list at
                # four ✓ is what made an accepted board render as "all done" above "0
                # open jobs" for as long as the harvest took: a complete checklist over
                # an empty company reads as "we finished and there was nothing there".
                ledger.start(STEP_FIRST_SCAN)
                return DiscoveryOutcome(
                    ok=True,
                    script=script,
                    transport=transport,
                    oracle_kind=script["oracle"]["kind"],
                    attempts=round_number,
                    cost_note=(
                        f"1 browser capture + {round_number} Haiku selection(s); "
                        f"replays as {transport}"
                        + (
                            f"; PARTIAL — reaches {coverage.reachable} of {coverage.visible}"
                            if coverage.is_partial else ""
                        )
                    ),
                    # The rows the ACCEPTANCE REPLAY returned — the same bytes the
                    # nightly harvest will read, not the capture's. Showing the user
                    # jobs that only our production path can actually see is the whole
                    # claim we are making by promising to track this board.
                    progress=ledger.snapshot(
                        outcome=(
                            OUTCOME_PARTIAL if coverage.is_partial else OUTCOME_TRACKING
                        ),
                        job_preview=rows,
                    ),
                )
            # This candidate cannot be replayed either way. TELL THE MODEL WHAT WE
            # MEASURED, then ask again — over what is left if anything is, and over the
            # SAME candidate if it is the only one there is.
            #
            # THE SECOND HALF IS THE FIX FOR A REAL GAP. ``_MAX_SELECTION_ROUNDS`` fires
            # on an acceptance failure, not just a schema failure — but the drop below
            # used to be unconditional, so a SINGLE-FEED board emptied the list and the
            # ``if not candidates: break`` at the top of the loop ended the discovery
            # before round two could happen. Atlassian and Jane Street each publish
            # exactly one jobs feed, so the boards that most needed a second ask were
            # precisely the ones that never got one.
            #
            # WHY THE DROP STILL HAPPENS WHEN THERE IS SOMETHING ELSE TO ASK ABOUT. The
            # next round's schema still demands an answer over whatever it is shown, and
            # the acceptance gate cannot save us: it proves the replay reads the SAME
            # array the browser saw, so a forced pick of a leftover facet/filter
            # catalogue overlaps itself 100% and is ACCEPTED. Measured on the TikTok
            # capture — with the jobs POST dropped, discovery stored ``…/job/filters``
            # (records_path ``data.job_category_list``) and tracked "Engineering" and
            # "Design" as the company's job postings, forever, with a nightly harvest
            # that would never fail.
            #
            # The floor is the FAILED candidate's own score, not the pre-filter's top
            # rank: the pre-filter is deliberately dumb and the model correcting it is a
            # designed path, so "must be the highest-ranked" would refuse boards we can
            # read. "Not less job-shaped than the thing that just failed" costs nothing
            # real and removes the manufactured answer.
            feedback = _selection_feedback(last_error, selection, link_why)
            floor = candidate.job_score
            survivors = [
                c for c in candidates
                if c.index != candidate.index and c.job_score >= floor
            ]
            # The failed candidate AS THE MODEL SAW IT — not the rebound-and-widened one
            # this round derived, which carries a records_path the model never proposed.
            sole = [c for c in candidates if c.index == candidate.index]
            candidates = [replace(c, index=i) for i, c in enumerate(survivors or sole)]

        raise _Refusal(
            last_step,
            last_error or "we could not replay any of this board's requests",
        )

    except _Refusal as exc:
        logger.warning("capture discovery REFUSED %s — %s", url, exc)
        # The ✕ lands on the step that actually decided it, and it OVERRIDES a step
        # already ticked: "found 3 candidate feeds ✓" followed by "none of them is a
        # jobs list" is one step's story, and showing the ✓ would be a lie about the
        # only thing the user needs to know.
        ledger.fail(_STEP_TO_CHECKLIST.get(exc.step, STEP_VERIFY_READ), exc.detail)
        return DiscoveryOutcome(
            ok=False,
            refuse_reason=str(exc),
            attempts=attempts,
            progress=ledger.snapshot(outcome=OUTCOME_REFUSED),
        )
    except Exception as exc:  # noqa: BLE001
        # BROAD ON PURPOSE. The caller is a retry=1 task whose provisional
        # ``discovering`` row is cleared only by an outcome being RETURNED; an escaping
        # exception leaves that row stuck at "Setting up…" with no way out but Remove +
        # re-add. A loud refusal carrying the exception type is strictly better than a
        # wedged row, and the log line below keeps the stack.
        logger.exception("capture discovery crashed for %s", url)
        ledger.fail(
            _STEP_TO_CHECKLIST.get(current_step, STEP_VERIFY_READ),
            f"something went wrong on our side ({type(exc).__name__})",
        )
        return DiscoveryOutcome(
            ok=False,
            # The step we had actually REACHED, not a hardcoded one. The refusal string
            # is rendered to the user and drives their next action, so telling someone
            # whose LLM call blew up that we failed "verifying we can read it" points
            # them at the wrong problem entirely.
            refuse_reason=f"{current_step}: discovery failed unexpectedly "
                          f"({type(exc).__name__})",
            attempts=attempts,
            progress=ledger.snapshot(outcome=OUTCOME_REFUSED),
        )
