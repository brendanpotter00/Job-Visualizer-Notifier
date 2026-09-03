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
4. :data:`_STEP_SELECT` — ONE Haiku call PER CANDIDATE ARRAY, in parallel: is this a
   list of job postings, and how do its fields map? Code then RANKS the yeses on
   measurements the board published about itself (:func:`_rank_answers`).
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
does not, decided once, here. What the capture reads is wider than the network log —
the SERVED document and the JSON islands inside it are candidates too, replayed as
``http_html``, and the board's own ``robots.txt``/``sitemap.xml`` supply counts no
browser could ever observe — but every one of them is a DETERMINISTIC replay or it is
not stored. Refusing is how we never wrong-track. Two shapes of that,
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
from typing import Any, Awaitable, Callable, Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

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
    composite_param_pattern,
    find_body_param_path,
    iter_body_params,
    iter_composite_query_params,
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
    CandidateAnswer,
    NoJobsFeedError,
    PaginationHint,
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
    select_candidates,
    session_token_keys,
)
from .sources import (
    SitemapMatch,
    WellKnownEvidence,
    collect_well_known,
    document_candidates,
    sitemap_match,
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
# Source 5's seam — :func:`sources.collect_well_known` or a $0 test double. Injectable
# for the same reason ``probe_link`` is: the real one reaches the public internet, and
# no unit test may do that.
WellKnownFn = Callable[[str], Awaitable[WellKnownEvidence]]


async def _abandon(task: "asyncio.Future[Any]") -> None:
    """Cancel a side task and swallow its ending. Never raises.

    A cancelled task nobody awaits produces "Task exception was never retrieved" noise
    at interpreter shutdown, and the one place this is used is a refusal path — the log
    line the user's failure is diagnosed from must not be buried under it.
    """
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        # ...unless it is OUR OWN cancellation passing through, which must never be
        # swallowed: the discovery task's 240 s guard is exactly that, and a coroutine
        # that eats its own CancelledError is a task that will not die.
        if not task.cancelled():
            raise
    except Exception:  # noqa: BLE001 - abandoning it, by name
        logger.debug("abandoned side task ended in an error", exc_info=True)


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
    """The selection seam — :func:`request_selector.select_candidates` or a $0 double.

    It answers about EVERY candidate now, not about the list. A Protocol rather than a
    ``Callable`` alias because of ``feedback``: a second round that cannot say WHY the
    first was rejected is a re-roll of the same question over the same bytes, which is
    the least likely way to get a different answer.
    """

    def __call__(
        self, candidates: list[Candidate], *, feedback: str | None = None
    ) -> Awaitable[list[CandidateAnswer]]: ...


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


def _is_form_capture(candidate: Candidate) -> bool:
    """Did the board's own request declare an ``x-www-form-urlencoded`` body?

    Read off the CAPTURED request header, never guessed from the body's shape: almost
    any string parses as a degenerate form ("hello" is one blank-valued field), so
    sniffing would turn a body we genuinely cannot read into a body we misread. The
    header is the board's own statement about its bytes, which is the standard every
    other derived part of the recipe is held to.
    """
    for name, value in (candidate.request_headers or {}).items():
        if str(name).lower() == "content-type":
            return "x-www-form-urlencoded" in str(value).lower()
    return False


def _post_body(candidate: Candidate) -> tuple[dict[str, Any], str]:
    """The captured POST body as ``(object, body_encoding)``, or raise a refusal.

    ``recipe_schema`` requires ``fetch.body`` to be an object because that is what the
    pagination merge writes into. Until Stage 2 that also meant JSON was the only body a
    recipe could carry, so a form-encoded request was refused outright — and
    metacareers.com is exactly that board: its jobs GraphQL answers 200 with 876 records
    to a form body and **400** to the same fields as JSON, so "we cannot replay this"
    was true only of our vocabulary.

    A form capture becomes a FLAT dict plus ``body_encoding='form'``. Flat is not a
    simplification, it is the wire format; a duplicate field name is refused because a
    dict cannot round-trip it and the second value would be silently dropped.
    """
    if _is_form_capture(candidate):
        pairs = parse_qsl(candidate.post_data or "", keep_blank_values=True)
        if not pairs:
            raise _Refusal(
                _STEP_SYNTHESIZE,
                "the jobs request declares a form-encoded body but we recorded no "
                "fields in it",
            )
        names = [name for name, _ in pairs]
        if len(set(names)) != len(names):
            raise _Refusal(
                _STEP_SYNTHESIZE,
                "the jobs request POSTs a form body with repeated field names, which "
                "the recipe vocabulary cannot express without dropping one",
            )
        return {name: value for name, value in pairs}, "form"
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
    return parsed, "json"


def _inband_error_keys(payload: Any) -> list[str]:
    """Top-level keys whose CAPTURED value is falsy — the board's success sentinels."""
    if not isinstance(payload, dict):
        return []
    return [k for k in _INBAND_ERROR_KEY_CANDIDATES if k in payload and not payload[k]]


def _leads_to_records(path: str, records_path: str) -> bool:
    """Is ``path`` a strict ancestor of ``records_path``? ``*`` matches any index."""
    want = records_path.split(".")
    got = path.split(".")
    if len(got) >= len(want):
        return False
    return all(w in (g, RECORDS_WILDCARD) for w, g in zip(want, got))


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

    THE WALK ENTERS A LIST ONLY ALONG THE RECORDS PATH, and it used not to enter one at
    all. Oracle Fusion wraps its ENTIRE envelope in a one-element list — ``items[0]``
    holds ``requisitionList`` and ``TotalJobsCount: 7181`` as siblings — so a dict-only
    walk never reached the total, and ``jpmc.fa.oraclecloud.com`` stored
    ``self_consistent`` while :func:`_totals_beside_records` (which walks UP from the
    records path, and decides the coverage verdict) read 7,181 out of the very same
    bytes. Two functions disagreeing about whether a board declares a total is a bug on
    its own.

    "Only along the records path" is the whole safety of it, and the alternative was
    MEASURED to be wrong. Walking every list finds careers.kakao.com's
    ``jobTypeCountDtoList[2].jobCount = 14`` — one tab's count on a capture of a
    DIFFERENT 8-job tab — and "largest wins" then makes 14 the declared total of a board
    that returns 8. A list element that is an ancestor of ``records_path`` is the same
    envelope the records live in; any other list is a facet block, whose buckets are
    counts of something else.
    """
    if not isinstance(payload, (dict, list)):
        return None
    best: tuple[int, int, str] | None = None      # (value, -depth, path)
    frontier: list[tuple[Any, str, int]] = [(payload, "", 0)]
    while frontier:
        node, path, depth = frontier.pop(0)
        if depth > _MAX_TOTAL_SEARCH_DEPTH:
            continue
        if isinstance(node, list):
            for index, element in enumerate(node):
                child_path = f"{path}.{index}" if path else str(index)
                if isinstance(element, (dict, list)) and _leads_to_records(
                    child_path, records_path
                ):
                    frontier.append((element, child_path, depth + 1))
            continue
        if not isinstance(node, dict):
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
            elif isinstance(value, list) and _leads_to_records(child_path, records_path):
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
    script: dict[str, Any],
    candidate: Candidate,
    selection: RequestSelection,
    *,
    extra_claims: Sequence[tuple[int, str]] = (),
) -> _Coverage:
    """Measure the stored recipe against the board's own published counts.

    ``extra_claims`` is how a source OTHER than the candidate's own payload gets a vote
    — the sitemap's matching-``<loc>`` count is the one that matters. Nothing about a
    claim cares which source produced it: they are all lower bounds the board published
    about ITSELF, and the biggest is the strongest statement that we are short. That is
    the entire mechanism by which the one source the page never requests can kill a
    wrong answer derived from a source it did.
    """
    reachable = _reachable_records(script, candidate)
    feed_reach = _feed_reach(script, candidate)
    payload, records_path = candidate.payload, selection.records_path
    claims: list[tuple[int, str]] = list(extra_claims)

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


def _sitemap_evidence(
    well_known: WellKnownEvidence,
    candidate: Candidate,
    selection: RequestSelection,
    origin_url: str,
) -> SitemapMatch | None:
    """Which sitemap (if any) enumerates the jobs THIS candidate returned.

    Matched on the ids the capture browser actually saw, mapped through the same field
    map the recipe uses — the same discipline :func:`_capture_ids` follows, and for the
    same reason: deriving ids two different ways compares the mappers, not the boards.

    ``None`` on every board without a sitemap, on every board whose sitemap does not
    carry our ids, and on any error at all. That is three boards in four and it has to
    cost nothing.
    """
    if not well_known.sitemaps:
        return None
    try:
        ids = _capture_ids(candidate, selection, _origin_of(origin_url))
    except Exception:  # noqa: BLE001 - a mapping failure here is not a discovery failure
        return None
    match = sitemap_match(well_known, ids)
    if match is None:
        return None
    logger.info(
        "sitemap %s lists %d page(s) under %r and carries %d of the %d captured job id(s)",
        match.sitemap_url, match.loc_count, match.url_pattern,
        len(match.matched_ids), len(ids),
    )
    return match


# --------------------------------------------------------------------------
# THE REFEREE — code MEASURES, and for now code alone DECIDES
# --------------------------------------------------------------------------
# The fan-out can come back with several candidates that are all "a list of job
# postings". Which one gets stored is settled on MEASUREMENTS, never on the model's
# ranking — that is the whole point of asking one question per array instead of asking
# one model to rank them. ``confidence`` is the last tie-break, used only after every
# measurement has tied.
#
# There is deliberately NO model-interpreted check here. Where the measurements are
# ambiguous the answer is the conservative one (a lower rank, or a refusal at the
# coverage floor), which is the safe half of every ambiguity.
#
# ``http_json`` outranks ``browser_fetch`` because it costs $0 a night, and both outrank
# ``http_html`` because the html executor cannot paginate at all — a board readable both
# ways should be read the way that can see all of it.
_TRANSPORT_RANK = {"http_json": 2, "browser_fetch": 1, "http_html": 0}


def _published_claims(candidate: Candidate, records_path: str) -> list[int]:
    """Every count the board publishes about itself, beside THESE records."""
    payload = candidate.payload
    return [
        n for n in (
            _totals_beside_records(payload, records_path, candidate.record_count),
            _facet_consensus_total(payload, records_path),
            _labelled_facet_total(payload, records_path),
        ) if isinstance(n, int) and n > 0
    ]


def _precoverage_ratio(candidate: Candidate, selection: RequestSelection) -> float:
    """How much of the board this candidate could reach, BEFORE anything is replayed.

    The same question :attr:`_Coverage.is_refused` asks and the same answer shape, but
    computed from the captured bytes alone so it can ORDER the candidates before we
    spend a replay on any of them. A candidate the board's own numbers say is 0.02% of
    itself sorts below one that is 100% of itself, and Walmart's chat endpoint is
    exactly that: ten records beside a self-declared 47,298.

    A candidate with a paging hint is treated as reaching the whole board, for the
    reason ``_feed_reach`` gives: what our own budget can spend is not a statement about
    the feed.
    """
    if selection.pagination is not None:
        return 1.0
    claims = _published_claims(candidate, selection.records_path)
    if not claims:
        return 1.0
    return min(1.0, candidate.record_count / max(claims))


def _oracle_strength(candidate: Candidate, selection: RequestSelection) -> int:
    """2 = the board publishes a trusted total, 1 = a real sweep, 0 = no claim at all.

    Straight from ``synthesize_recipe``'s own oracle decision, so the ranking prefers
    the candidate that will end up with the completeness claim that can actually
    VERIFY — which is the difference between a board that closes jobs correctly and one
    that is UNVERIFIED forever.
    """
    total_path = _find_total_path(
        candidate.payload, selection.records_path, candidate.record_count
    )
    if total_path:
        return 2
    return 1 if selection.pagination is not None else 0


def _rank_answers(
    answers: list[CandidateAnswer], candidates: list[Candidate]
) -> list[CandidateAnswer]:
    """Order the model's yeses by what we MEASURED about each one. Best first."""
    def _key(answer: CandidateAnswer) -> tuple[Any, ...]:
        candidate = candidates[answer.candidate_index]
        selection = answer.selection
        assert selection is not None            # only yeses reach the referee
        return (
            # C15 FIRST, as a demotion and never a verdict. A request carrying a
            # thread/session/conversation id is textbook birth-defect shape — it passes
            # acceptance BY CONSTRUCTION, because acceptance runs minutes later while
            # the token is still alive — but code cannot prove the key is fatal, so it
            # sorts below every candidate without one and decides nothing.
            not session_token_keys(candidate),
            _precoverage_ratio(candidate, selection),
            _oracle_strength(candidate, selection),
            _TRANSPORT_RANK["http_html" if candidate.html is not None else "http_json"],
            candidate.job_score,
            1 if answer.confidence == "high" else 0,
        )
    return sorted(answers, key=_key, reverse=True)


def _sitemap_claims(match: SitemapMatch | None) -> tuple[tuple[int, str], ...]:
    """The sitemap's ``<loc>`` count, as a coverage claim. Empty when there is none."""
    if match is None or match.loc_count <= 0:
        return ()
    return ((
        match.loc_count,
        f"this board's own sitemap lists {match.loc_count:,} job page(s)",
    ),)


# The oracles a sitemap may REPLACE, and it is deliberately not "any of them".
#
# ``declared_probed`` and ``facet_sum`` already carry a trusted total out of bytes we
# were downloading anyway; swapping one of those for a sitemap buys nothing and costs a
# 2 MB GET every night forever. The two below are the HISTORICAL oracles — neither has a
# trusted total, ``none`` can never be VERIFIED at all, and both are exactly the boards
# §4.2 wants to give a completeness claim to. So the attach is only ever an upgrade.
_SITEMAP_UPGRADABLE_ORACLES = frozenset({"none", "self_consistent"})


def _attach_sitemap_oracle(
    script: dict[str, Any],
    match: SitemapMatch | None,
    rows: list[dict],
    candidate: Candidate,
    selection: RequestSelection,
    origin_url: str,
) -> dict[str, Any]:
    """Promote the sitemap from a coverage CLAIM to the stored completeness ORACLE.

    The ``sitemap`` oracle has been implemented end to end since Phase 3a — admitted by
    the schema, shape-validated, computed at replay on both transports, verified into a
    verdict, unit-tested — and discovery has never emitted one, because its oracle
    decision could only ever produce ``declared_probed``, ``self_consistent`` or
    ``none``. This is the three lines that were missing, plus the rule that makes them
    safe.

    TWO CONDITIONS, AND THEY ANSWER DIFFERENT QUESTIONS.

    * **id overlap** proves it is the SAME BOARD. Without it we would attach the sitemap
      of whatever site the careers page lives on.
    * **exact agreement** proves the oracle is USABLE. ``_verify_oracle_total`` is
      tolerance 0: a sitemap oracle VERIFIES only when tonight's post-dedup count
      exactly equals the ``<loc>`` count. On a board where those two numbers do not
      already agree, attaching one replaces an oracle that can verify with one that
      structurally cannot, forever.

    Overlap alone is not enough and Walmart is why: its chat endpoint returns REAL
    Walmart job ids, so ten of ten would be found in the sitemap. **The count is what
    kills it.** Overlap proves same-board; count proves whole-board.

    Returns the script unchanged whenever anything does not line up — which is most
    boards, and has to cost nothing.
    """
    if match is None or match.loc_count <= 0:
        return script
    if script["oracle"]["kind"] not in _SITEMAP_UPGRADABLE_ORACLES:
        return script
    # (a) SAME BOARD.
    try:
        captured = _capture_ids(candidate, selection, _origin_of(origin_url))
    except Exception:  # noqa: BLE001 - an unmappable capture is simply no evidence
        return script
    floor = max(1, int(len(captured) * _MIN_ID_OVERLAP_RATIO))
    if len(match.matched_ids) < floor:
        logger.info(
            "sitemap %s carries only %d of the %d captured job id(s) — not this board's "
            "own catalogue, keeping oracle %r",
            match.sitemap_url, len(match.matched_ids), len(captured),
            script["oracle"]["kind"],
        )
        return script
    # (b) WHOLE BOARD. The acceptance replay is clamped to two pages on purpose, so on a
    # paginated board this is essentially never true and the oracle stays where it was —
    # which is the conservative outcome §4.2 asks for, reached without a special case.
    if len(rows) != match.loc_count:
        logger.info(
            "sitemap %s lists %d page(s) but the replay reads %d — a tolerance-0 oracle "
            "that never matches is worse than none, keeping oracle %r",
            match.sitemap_url, match.loc_count, len(rows), script["oracle"]["kind"],
        )
        return script

    upgraded = dict(script)
    upgraded["oracle"] = {
        "kind": "sitemap",
        "sitemap_url": match.sitemap_url,
        "url_pattern": match.url_pattern,
    }
    try:
        validate_recipe(
            upgraded, transport=upgraded["transport"], oracle_kind="sitemap"
        )
    except RecipeError as exc:
        # A recipe we cannot validate is one we do not store. Degrading to the oracle
        # discovery already chose keeps a board we can read.
        logger.warning(
            "sitemap oracle for %s did not validate (%s) — keeping oracle %r",
            match.sitemap_url, exc, script["oracle"]["kind"],
        )
        return script
    logger.info(
        "attached a sitemap oracle for %s: %d <loc> under %r == %d replayed row(s), "
        "and %d of %d captured id(s) appear in it (was %r)",
        match.sitemap_url, match.loc_count, match.url_pattern, len(rows),
        len(match.matched_ids), len(captured), script["oracle"]["kind"],
    )
    return upgraded


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


# Offset-token names a COMPOSITE query value may carry. Matched EXACTLY, not by
# substring: ``start`` must not match ``startDate`` and ``from`` must not match
# ``fromLocation``, because a cursor written over a date is a request the board answers
# with something other than page two.
_COMPOSITE_OFFSET_NAMES = frozenset({
    "offset", "from", "start", "startindex", "startrow", "skip", "firstresult",
})


def _composite_pagination(candidate: Candidate) -> PaginationHint | None:
    """An OFFSET paging hint read out of a composite query value, or ``None``.

    THE PARAMETER THE MODEL CANNOT SEE. Oracle Fusion Recruiting — the ATS behind
    ``jpmc.fa.oraclecloud.com`` and a very large slice of enterprise employers — carries
    its whole search in one query value::

        finder=findReqs;siteNumber=CX_1001,facetsList=...,limit=25,sortBy=...,offset=75

    The selector prompt asks for "an obvious paging parameter you can see in its URL",
    and measured 2026-08-30 the model answered ``pagination: null`` on **6 of 6**
    candidates for this board — correctly, by its own instructions: ``offset`` is not a
    parameter of that URL, it is a token inside one. No paging step was synthesised, the
    recipe reached 25 of a self-declared 7,181, and the coverage floor refused the board.

    So this is DERIVED from the captured bytes rather than asked, which is the same rule
    :func:`_page_size_param` and :func:`_captured_start_page` already follow, and for the
    same reason: a guessed cursor is a silently-short sweep, and a short sweep that looks
    complete is the wrong-close direction.

    OFFSET ONLY, deliberately. An offset sweep always starts its cursor at 0, so there is
    no base to get wrong. A composite ``page=N`` would need a ``start_page``, and
    :func:`_captured_start_page` reads only real query parameters and real body slots —
    guessing 1 for a 0-based board skips its entire first page and still ends on a short
    page, which is exactly the higher.gs.com bug. Such a board keeps today's behaviour
    (no paging, and the coverage floor or check 13 decides) until someone measures one.
    """
    for _container, name, value in iter_composite_query_params(candidate.url):
        if name.lower() not in _COMPOSITE_OFFSET_NAMES:
            continue
        logger.info(
            "derived an offset paging hint %r=%s from a composite query value on %s "
            "— the model cannot see this parameter and answered null",
            name, value, candidate.url,
        )
        return PaginationHint(
            style="offset", param=name, page_size=candidate.record_count
        )
    return None


# The cursor token seeded into a composite value that carries a page size but no
# offset. ONE name, and the one that pairs with ``limit`` in every REST convention
# this shape comes from (OData ``$top``/``$skip`` aside). It is never trusted on the
# strength of the name — :func:`_seed_composite_offset` FETCHES it and keeps it only
# if the board answered with a different page.
_SEEDED_COMPOSITE_OFFSET = "offset"


async def _seed_composite_offset(
    candidate: Candidate, selection: RequestSelection, probe: ProbeFn
) -> Candidate | None:
    """``candidate`` with a PROVEN ``offset=0`` written into its composite, or ``None``.

    THE PAGE THE BOARD NEVER ASKED FOR. :func:`_composite_pagination` can only read a
    cursor the capture SAW, and a board only shows one if it happens to fetch page two
    while we are watching. Measured 2026-08-30 on two Oracle Fusion Recruiting tenants —
    the same ATS, the same ``finder=findReqs;…,limit=N,…`` grammar, the same
    ``TotalJobsCount`` oracle:

    * ``jpmc.fa.oraclecloud.com`` INFINITE-SCROLLS. ``_settle``'s scroll made it fetch
      ``offset=25,50,75,100`` unprompted, the capture recorded those URLs, and the board
      discovers today (7,124 rows over 285 pages).
    * ``careers.oracle.com`` paginates with a **SHOW MORE RESULTS button**. Scrolling
      fetches nothing, so every captured URL reads ``limit=14`` with no offset token, no
      paging step is synthesised, and check 13b refuses the board ``page_limit_reached``
      at 14 of a declared 1,612.

    Nothing about the FEED differs — only whether the site's paging control happens to
    fire on scroll. That is not a property a board should be judged on, so the cursor is
    seeded rather than waited for.

    SEEDED AS ``offset=0`` INTO THE CAPTURED URL, not carried as a side-channel, and that
    is what keeps this small: the rewritten URL is a first page byte-for-byte (verified
    live — identical ids to the unseeded request), so :func:`_composite_pagination` finds
    the token by its normal path, ``merge_query_params`` writes the cursor WHERE IT NOW
    ALREADY IS instead of appending a ``&offset=`` the board would ignore, and check 13,
    the coverage floor and ``_assert_matches_capture`` all reason about one URL.

    PROVEN, NEVER GUESSED — the standard :func:`_composite_pagination` sets. We fetch
    page two through the SSRF-guarded probe seam and keep the seed only if the board
    answered with a non-empty, DISJOINT set of records. A board that ignores the token
    re-serves page one and is rejected here; a board that rejects it outright fails the
    probe and is rejected here. Either way the board keeps today's refusal rather than
    gaining a paginator that silently re-reads page one — the wrong-close direction.
    """
    # An XHR/fetch GET only: ``http_html`` may never paginate (``validate_recipe``
    # rejects it) and a POST carries its cursor in the body, which is a different seam.
    if candidate.html is not None or candidate.method != "GET":
        return None
    if candidate.record_count <= 0:
        return None
    # A cursor the capture already showed us is _composite_pagination's job, and a
    # board whose own total says the captured page IS the board must not gain a paging
    # step it does not need — ``one_page_proven`` would drop it and check 13a would then
    # refuse the seeded ``offset`` as an unpaginated page parameter.
    tokens = list(iter_composite_query_params(candidate.url))
    if any(name.lower() in _COMPOSITE_OFFSET_NAMES for _c, name, _v in tokens):
        return None
    declared = _declared_total(candidate, selection)
    if declared is not None and declared <= candidate.record_count:
        return None
    # THE ANCHOR IS THE PAGE SIZE, not the name of the container. ``_is_page_size``
    # requires the token to both NAME a size and equal the number of records that came
    # back, which is what tells us this composite is the one the board paged on.
    anchor = next(
        (
            (container, name)
            for container, name, value in tokens
            if _is_page_size(name, value, candidate.record_count)
        ),
        None,
    )
    if anchor is None:
        return None
    container, size_name = anchor
    probe_url = _write_composite_offset(
        candidate.url, container, size_name, candidate.record_count
    )
    status, body = await asyncio.to_thread(probe, probe_url)
    if status != 200 or not body:
        logger.info(
            "composite offset seed rejected for %s: HTTP %s asking for %s=%d",
            candidate.url, status, _SEEDED_COMPOSITE_OFFSET, candidate.record_count,
        )
        return None
    try:
        page_two = dig_records(json.loads(body, strict=False), candidate.records_path)
    except (ValueError, RecipeError, TypeError) as exc:
        logger.info(
            "composite offset seed rejected for %s: page two did not parse at %r (%r)",
            candidate.url, candidate.records_path, exc,
        )
        return None
    if not isinstance(page_two, list) or not page_two:
        logger.info(
            "composite offset seed rejected for %s: page two held no records at %r",
            candidate.url, candidate.records_path,
        )
        return None
    first = {_record_fingerprint(record) for record in candidate.records}
    second = {_record_fingerprint(record) for record in page_two}
    if not first.isdisjoint(second):
        logger.info(
            "composite offset seed rejected for %s: %r=%d re-served %d of page one's "
            "%d record(s) — this board does not read that token",
            candidate.url, _SEEDED_COMPOSITE_OFFSET, candidate.record_count,
            len(first & second), len(first),
        )
        return None
    seeded = _write_composite_offset(candidate.url, container, size_name, 0)
    logger.info(
        "seeded a PROVEN %r cursor beside %r in the composite %r of %s — page two "
        "returned %d record(s), none of them page one's",
        _SEEDED_COMPOSITE_OFFSET, size_name, container, candidate.url, len(page_two),
    )
    return replace(candidate, url=seeded)


def _write_composite_offset(
    url: str, container: str, size_name: str, cursor: int
) -> str:
    """``url`` with ``offset=<cursor>`` written immediately after the page-size token.

    Beside the page size on purpose: that is the token we PROVED this board pages on,
    so it is the composite value — and the position inside it — the cursor belongs to.
    The re-encode is ``merge_query_params``' own, so a seeded URL and a swept one are
    spelled identically.
    """
    rewritten: list[tuple[str, str]] = []
    for name, raw in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if name == container:
            raw = composite_param_pattern(size_name).sub(
                lambda m: f"{size_name}={m.group('value')}"
                f",{_SEEDED_COMPOSITE_OFFSET}={cursor}",
                raw,
                count=1,
            )
        rewritten.append((name, raw))
    return str(httpx.URL(url).copy_with(query=urlencode(rewritten).encode()))


def _record_fingerprint(record: Any) -> str:
    """A stable identity for one record, for comparing two pages of the same feed."""
    try:
        return json.dumps(record, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str takes everything
        return repr(record)


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
    if selection.pagination is None or candidate.html is not None:
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


def _extraction_step(
    candidate: Candidate, selection: RequestSelection
) -> dict[str, Any]:
    """The extraction op this candidate replays through.

    ``extract_css`` deliberately does NOT take the model's field map: an ``<a href>``
    carries exactly a link and a label, the selectors were derived from the served
    document, and re-mapping them through dotted paths would be re-answering a question
    that has no second answer. The other two take it.
    """
    html = candidate.html
    if html is None:
        return {
            "op": "extract_json_path",
            "records_path": selection.records_path,
            "fields": dict(selection.field_map),
        }
    if html.op == "extract_css":
        return {
            "op": "extract_css",
            "record_selector": html.selector,
            "field_selectors": dict(html.field_selectors or {}),
        }
    step: dict[str, Any] = {
        "op": "extract_embedded_island",
        "selector": html.selector,
        "source": html.source,
        "records_path": selection.records_path,
        "fields": dict(selection.field_map),
    }
    if html.source == "attribute":
        step["attribute"] = html.attribute
    return step


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
        "url": candidate.html.document_url if candidate.html else candidate.url,
        "headers": {} if candidate.html else _clean_headers(candidate.request_headers),
    }
    if candidate.method == "POST" and candidate.html is None:
        # ``body_encoding`` is written only when it is NOT the default, so a JSON board's
        # stored recipe is byte-identical to the one this function produced before
        # Stage 2 — the diff between two nightly recipes has to stay readable.
        fetch["body"], body_encoding = _post_body(candidate)
        if body_encoding != "json":
            fetch["body_encoding"] = body_encoding

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
    # ...and NEVER on ``http_html``. ``validate_recipe`` rejects it (``_run_http_html``
    # issues one request and reports a clean complete sweep, so a paginating html recipe
    # would read as complete and close every job past page one) — building one only to
    # be refused would turn a readable single-page board into a refusal.
    if selection.pagination is not None and not one_page_proven and candidate.html is None:
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

    # THE EXTRACTION, and the one place a DOCUMENT candidate diverges from an XHR one.
    # Both ``extract_embedded_island`` and ``extract_css`` have been implemented in
    # ``recipe_runner`` since Phase 3a and discovery has never emitted either; the
    # transport that replays them, ``http_html``, has likewise never been emitted.
    steps.append(_extraction_step(candidate, selection))

    # THE TITLE, when the board publishes only a link (PATH-TO-90-PERCENT.md §6 Stage 2).
    # ``transform`` has existed since Phase 3a with two kinds and discovery has emitted
    # neither; ``regex_capture`` is the third and this is the one place that emits it.
    # The pattern is not the model's — ``derive_title_from_url`` proved it against the
    # captured records through the very function the runner replays it with — so the
    # only thing decided here is whether to write the step down.
    #
    # Emitted AFTER the extraction and BEFORE ``parse_date`` because ``_apply_shaping``
    # runs steps in order and this one has to see the mapped row, not the raw record.
    if selection.title_from_url is not None:
        steps.append({
            "op": "transform",
            "field": "title",
            "kind": "regex_capture",
            "from": "url",
            "pattern": selection.title_from_url.pattern,
            "unslug": selection.title_from_url.unslug,
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

    ``select_candidates`` already proved the path resolves; the guard is for an injected
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
#
# THE ABSOLUTE BOUND WAS 200 AND IT REJECTED A CORRECT BOARD. Measured on YC/Raindrop:
# 7,088 vs 6,936 chars — a 152-char difference against a 2% bar of 141, so the FRACTION
# said "different" and the flat 200 overruled it. That is the bound working backwards:
# on a 7 KB page the absolute is the stricter of the two, which is the opposite of the
# job the comment above gives it.
#
# 120 is where the corpus puts it, not a taste. Across the 13 boards in
# ``fixtures/job_links`` plus the 10 re-measured on 2026-08-30, EVERY wrong template
# serves byte-identical pages — Goldman's dead key 23 vs 23, Walmart 1,606 vs 1,606,
# Kakao 53 vs 53, Nintendo 842 vs 842, Atlassian 18,076 vs 18,076, JPMorgan 30 vs 30 —
# and the smallest difference any CORRECT link produced is Roblox's 50 chars (0.8%).
# So every threshold in (0, 50) separates the corpus perfectly and 120 keeps a wide
# margin over the per-request nonce/CSRF/timestamp noise the bound exists for.
_MIN_PAGE_DELTA_CHARS = 120
_MIN_PAGE_DELTA_FRACTION = 0.02

# One probe fetch: ``url -> (status, body)``. A status of 0 means the fetch never
# happened (guard refusal, DNS, timeout, reset) and is treated exactly like a 500 —
# unproven, never fatal.
ProbeFn = Callable[[str], tuple[int, str]]

# WHO WE SAY WE ARE ON THE RETRY, and why the first attempt still says Chrome.
#
# ``guarded_sync_client`` sends the replay's Chrome User-Agent, and on three boards
# measured 2026-08-30 that string is ITSELF the failure: ``metacareers.com`` answers a
# real job page **HTTP 400** to Chrome and **200** to anything else. The plan said to
# stop sending a browser UA. Measured across 22 live job pages, doing that
# unconditionally trades one board for another:
#
#   * with no ``User-Agent`` header at all: ``higher.gs.com`` 403, ``janestreet.com``
#     403 — two working boards lost;
#   * with a non-browser UA (httpx's own or the string below): ``careers.roblox.com``
#     tarpits every request to a read timeout, reproducibly, three tries each.
#
# So the browser UA stays FIRST and this one is the RETRY, fired only when the board
# answered and refused (see ``_ANSWERED_BUT_REFUSED``). Roblox never reaches it (it
# answers 200 to Chrome), Goldman and Jane Street never reach it, and Meta does.
_PROBE_USER_AGENT = "onesecondswe-link-check/1.0 (+https://onesecondswe.dev)"

# A status that means "the board answered, and what it answered was about US" — a WAF
# challenge, a bot filter, a rate limit, a 400 on our own User-Agent. Worth exactly one
# retry with a different client identity. 404/410 are deliberately NOT here: they are
# the board answering about the URL, which is the question we asked.
_ANSWERED_BUT_REFUSED = frozenset({400, 401, 403, 405, 406, 409, 415, 429})
# The board said this page does not exist. The one status that is real evidence the
# template is WRONG rather than merely unproven.
_NOT_FOUND_STATUSES = frozenset({404, 410})

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>")
_TAG_RE = re.compile(r"<[^>]+>")
_META_RE = re.compile(r"(?is)<meta\b[^>]*>")
_META_TITLE_KEY_RE = re.compile(
    r"""(?is)(?:property|name)\s*=\s*["']?\s*(?:og:title|twitter:title)\s*["']?"""
)
_META_CONTENT_RE = re.compile(r"""(?is)\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_TITLE_TAG_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title\s*>")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "‐": "-", "‑": "-", "‒": "-", "–": "-",
                         "—": "-", "―": "-"})


def _default_probe(url: str) -> tuple[int, str]:
    """GET ``url`` through the SAME SSRF-guarded client the nightly replay uses.

    Never raises: every failure is ``(0, "")``, because "we could not check" and "the
    check failed" lead to the same place — the link is unproven and will not be stored.
    Reusing ``guarded_sync_client`` is not incidental; this fetches a URL a model
    composed, which is the exact threat that client's host-pin and IP-pin exist for.

    Two deliberate differences from the replay's client, both measured:

    * ``allow_cross_host=True`` — a redirect to another host is FOLLOWED, with every
      hop re-validated and IP-pinned by the same guard (see ``guarded_sync_client``).
      Without it ``boards.greenhouse.io`` → ``job-boards.greenhouse.io`` (SpaceX) and
      ``databricks.com`` → ``www.databricks.com`` both reported "HTTP 0" and killed a
      correct recipe.
    * ONE retry under :data:`_PROBE_USER_AGENT` when the board answers with a status
      that is about our client rather than about the URL. Only fires on an answer, so
      a board that is timing out still costs exactly one timeout, and the ladder's
      worst case is the same wall clock it was before.
    """
    try:
        http = guarded_sync_client(allow_cross_host=True)
    except Exception:                       # pragma: no cover - client build cannot fail
        return 0, ""
    try:
        status, body = _probe_once(http, url, None)
        if status in _ANSWERED_BUT_REFUSED:
            retried, retried_body = _probe_once(http, url, _PROBE_USER_AGENT)
            logger.info(
                "job-link probe retried %s without the browser User-Agent: %d -> %d",
                url, status, retried,
            )
            if retried and retried not in _ANSWERED_BUT_REFUSED:
                return retried, retried_body
        return status, body
    finally:
        http.close()


def _probe_once(http: httpx.Client, url: str, user_agent: str | None) -> tuple[int, str]:
    """One bounded GET. ``(0, "")`` for anything that never produced a response."""
    headers = {"User-Agent": user_agent} if user_agent else None
    try:
        with http.stream(
            "GET", url, timeout=_LINK_PROBE_TIMEOUT_S, headers=headers
        ) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) >= _LINK_PROBE_MAX_BYTES:
                    break
            return response.status_code, bytes(body).decode("utf-8", "replace")
    except Exception as exc:                # noqa: BLE001 - every failure is "unproven"
        logger.info("job-link probe could not fetch %s: %r", url, exc)
        return 0, ""


def _page_text(body: str) -> str:
    """An HTML body reduced to comparable words.

    Scripts and styles go first and for a reason bigger than noise: an SPA's payload
    lives in a ``<script>`` tag, so a shell that renders nothing can still carry every
    job's title in its bundle. Stripping them is what makes "the page is about THIS
    job" mean the page, not the app.
    """
    text = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", body))
    return _normalize_words(text)


def _normalize_words(text: str) -> str:
    text = unicodedata.normalize("NFKD", html.unescape(text)).translate(_QUOTES)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _MULTISPACE_RE.sub(" ", text).strip().casefold()


def _declared_title(body: str) -> str:
    """WHAT THE PAGE SAYS IT IS — ``og:title``/``twitter:title``, else ``<title>``.

    THE SIGNAL :func:`_page_text` CANNOT SEE, and the reason the proof rejected five
    correct boards. ``_page_text`` strips ``<script>`` (rightly — an SPA bundle carries
    every job's title) and then strips tags, which deletes every ATTRIBUTE with them.
    A client-rendered job page's only server-delivered per-job fact is usually an
    ``og:title`` meta tag, i.e. an attribute. Measured 2026-08-30, all four served by
    plain httpx with no browser:

    ==================  =====================  ==================================
    board               ``_page_text`` says    this function says
    ==================  =====================  ==================================
    JPMorgan CX_1001    30 chars, both jobs    *AI Lead Security Engineer* /
                                               *Credit Card Customer Service …*
    Micron Workday      0 chars, both jobs     *TECHNOLOGIST - FAC UPW & WWTP* /
                                               *ENGINEER - FACILITIES CHEMICAL …*
    careers.oracle.com  6 chars, both jobs     *Oracle Database Administrator* /
                                               *Oracle WebLogic Consultant*
    metacareers.com     12 chars, both jobs    *Software Engineer, Machine …* /
                                               *Technical Program Manager, …*
    ==================  =====================  ==================================

    ``<title>`` is the fallback and not the first choice because a board is far more
    likely to leave it generic than to leave ``og:title`` generic: JPMorgan's is
    *"JPMC Candidate Experience page"* on every job, Oracle's is *"Oracle"*. It still
    earns its place — Micron's ``<title>`` is empty and YC/Raindrop has no ``og:title``
    difference the body lengths do not already carry.

    Returns ``""`` when the page declares nothing, which is not a failure: Walmart and
    Atlassian genuinely declare no title, and the caller falls back to comparing pages.
    """
    for meta in _META_RE.finditer(body):
        tag = meta.group(0)
        if not _META_TITLE_KEY_RE.search(tag):
            continue
        content = _META_CONTENT_RE.search(tag)
        if content is None:
            continue
        value = _normalize_words(next(g for g in content.groups() if g is not None))
        if value:
            return value
    title = _TITLE_TAG_RE.search(body)
    return _normalize_words(title.group(1)) if title else ""


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


@dataclass(frozen=True)
class LinkProof:
    """The proof's verdict, and the distinction the old ``str | None`` could not carry.

    ``proved`` and ``blocked`` are three states, not four: proved / **wrong** /
    **blocked**. The middle one is "we looked and the board told us this template does
    not point at one job" — a 404, or the same page served for two different ids.
    The third is "we never got to look": a WAF challenge, a bot filter, a 400 aimed at
    our own User-Agent, a timeout.

    THEY WERE THE SAME OUTCOME AND THAT IS THE BUG. Measured on IBM 2026-08-30, AWS WAF
    answers our probe **202 with an empty body** on every job page. Two empty bodies
    compare equal, so the proof reported *"two different jobs served the same page (0 vs
    0 chars)"* — a positive claim about the board, made out of bytes the board never
    sent. Rendered in Chromium the same two URLs are two different jobs with correct
    titles. Silence is not a denial; it has to be able to say so.
    """

    proved: bool
    blocked: bool
    why: str


_PROVED = LinkProof(proved=True, blocked=False, why="")


def _classify_page(status: int, body: str) -> tuple[str, LinkProof | None]:
    """``(page text, refusal)`` for one probe answer — refusal is ``None`` when usable.

    THE LINE BETWEEN "WRONG" AND "BLOCKED" IS DRAWN NARROWLY ON PURPOSE. Blocked means
    the board sent us **no document at all** — a status that is about our client, or a
    2xx with an empty body (IBM's AWS WAF answers ``202`` with zero bytes on every job
    page). It does NOT mean "a document we could not read anything out of": a
    ``<script>``-only SPA shell is thousands of bytes of real answer, and Goldman's dead
    ``{roleId}`` differed from a correct link by 23 of them. Widening blocked to cover
    empty-after-stripping would move that board from *disproved* to *unproven* — and
    ``_resolve_job_link`` keeps an unproven candidate. The 404 that this whole rule
    exists to stop would ship again.
    """
    if status in _NOT_FOUND_STATUSES:
        return "", LinkProof(False, False, f"HTTP {status} — the board says this page "
                                           "does not exist")
    if status == 0 or status >= 400:
        return "", LinkProof(False, True, f"HTTP {status or 'no answer'} — the board did "
                                          "not let us look at this page")
    if not body.strip():
        return "", LinkProof(False, True, f"HTTP {status} with an empty body — the board "
                                          "answered without serving a page")
    return _page_text(body), None


def _prove_job_link(
    records: list[Any], field_map: dict[str, str], base_url: str, probe: ProbeFn
) -> LinkProof:
    """Proved / wrong / blocked for this url spec. Sync; never raises.

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

    THREE WAYS TO SAY YES, tried in order of how much they claim. Each one on its own
    answers the only question being asked — *does this URL route on this id?*

    1. **the page carries this job's own title and not the other's** — the strongest,
       and the only one that also says the page is ABOUT the job;
    2. **the two pages DECLARE different titles** (:func:`_declared_title`) — the one
       that recovers every client-rendered board, because a 30-char shell still ships
       an ``og:title``;
    3. **the two pages are materially different lengths** — the original weak form.

    None of the three is a veto, and (2) especially must not be: SpaceX's Greenhouse
    board serves the same ``og:title`` on three genuinely different job pages, and
    Oracle can have two open reqs with one title. Equal declared titles mean *no
    evidence from titles*, never *no*.

    AND THE ONE SHAPE THAT STILL HAS TO FAIL. A board that answers every job URL with
    the same near-empty shell AND a generic declared title is refused — Kakao (53
    chars, *"카카오 영입"*, a correct template) fails exactly like Goldman's dead
    ``{roleId}`` (23 chars, *"Careers | Goldman Sachs"*) and Nintendo's embed (842
    chars, *"Careers at Nintendo - Join Our Team"*, the wrong page). Over plain HTTP
    those three are the same bytes, and there is no rule that keeps Kakao without
    resurrecting Goldman's 404. Refusing all three is the honest floor of a prover that
    does not render.
    """
    samples = _link_samples(records, field_map, base_url)
    if len(samples) < _LINK_PROBE_SAMPLES:
        return LinkProof(
            False, False,
            f"only {len(samples)} of the board's jobs render a distinct link",
        )

    pages: list[tuple[str, str, str]] = []
    for title, url in samples:
        status, body = probe(url)
        text, refusal = _classify_page(status, body)
        if refusal is not None:
            return replace(refusal, why=f"{refusal.why} ({url})")
        pages.append((title, text, _declared_title(body)))

    (feed_a, page_a, said_a), (feed_b, page_b, said_b) = pages
    if (
        feed_a != feed_b
        and min(len(feed_a), len(feed_b)) >= _DISTINCTIVE_TITLE_CHARS
    ):
        own = feed_a in page_a and feed_b in page_b
        cross = feed_a in page_b or feed_b in page_a
        if own and not cross:
            return _PROVED
    if said_a and said_b and said_a != said_b:
        return _PROVED
    if _pages_differ(page_a, page_b):
        return _PROVED
    return LinkProof(
        False, False,
        f"two different jobs served the same page ({len(page_a)} vs "
        f"{len(page_b)} chars"
        + (f", both titled {said_a!r}" if said_a and said_a == said_b else "")
        + ") — this link does not point at one job",
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
    4. **nothing proved, but the board never answered** — keep the best candidate the
       board's own evidence produced. A WAF challenge disproves nothing, and
       ``listing-page#{id}`` is certainly not a job link (see the ``blocked`` branch).
    5. **nothing proved** — :func:`_board_page_link`, and say so out loud.

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

    # The candidates the BOARD's own evidence produced, as opposed to the model's
    # invention. The distinction only matters when the board refuses to be probed —
    # see the ``blocked`` branch below.
    #
    # ``repaired`` HAS TO BE COMPARED, not just added. ``repair_url_template`` returns
    # the selection unchanged when it has nothing to swap, so on most boards it hands
    # back the model's OWN spec — and ``{*derived, repaired}`` therefore let the guess
    # straight back in through the evidence door. The first version of this line did
    # exactly that; ``test_ac21b_a_waf_does_not_promote_the_models_bare_guess`` is the
    # case that caught it.
    evidenced = {*derived} | ({repaired} if repaired != spec else set())

    tried: list[str] = []
    why = ""
    # A candidate we could not DISPROVE, only because the board would not let us look.
    # Kept as the answer of last resort ahead of the listing-page fallback, and only
    # for a template the board's own anchors, scripts or captured URLs support.
    unprovable: str | None = None
    for attempt in [*derived, repaired, spec]:
        if attempt in tried:
            continue
        if len(tried) >= _MAX_PROVE_ATTEMPTS or context.expired():
            logger.warning(
                "job-link proof budget spent after %d attempt(s) on %s", len(tried), origin_url
            )
            break
        tried.append(attempt)
        proof: LinkProof = await asyncio.to_thread(
            _prove_job_link, records, {**selection.field_map, "url": attempt},
            base_url, context.probe,
        )
        why = proof.why
        if proof.proved:
            logger.info("job link %r proved against the live board", attempt)
            return _with(attempt), True, ""
        if proof.blocked and unprovable is None and attempt in evidenced:
            unprovable = attempt
        logger.warning(
            "job link %r is %s: %s", attempt,
            "unproven — the board would not answer the probe" if proof.blocked
            else "not usable", why,
        )

    # NOT PROVED IS NOT THE SAME AS DISPROVED, and this is the whole of what that buys.
    # A board behind a WAF (IBM answers our probe 202/empty on every job page) tells us
    # NOTHING about a template — so falling back to ``listing-page#{id}``, which is
    # certainly not a job link, trades a probably-right link for a certainly-wrong one.
    #
    # Bounded on purpose: only a template the BOARD's own evidence produced is kept
    # this way. The model's bare guess is not — that is exactly Jane Street's
    # ``/jobs/{id}``, and if a board ever blocked us while the model guessed like that,
    # shipping it would undo the whole reason this ladder exists. A 404 or a
    # same-page-twice answer is still a hard no here, because those the board DID tell
    # us.
    if unprovable is not None:
        logger.warning(
            "job link %r could not be proved because %s would not answer the probe; "
            "keeping it — it is derived from the board's own links or scripts, and the "
            "listing-page fallback is certainly not a job link",
            unprovable, _hostname_of(origin_url),
        )
        return _with(unprovable), True, ""

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
    collect_sources: WellKnownFn | None = None,
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
    do_collect_well_known = collect_sources or collect_well_known
    do_select = select or select_candidates
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
        #
        # ...and, BESIDE it, the one source no browser can observe. Source 5 needs only
        # the entry URL and httpx, both of which exist before the subprocess spawns, so
        # it runs concurrently with a capture that takes 30-120 s and its own 15 s
        # ceiling is spent entirely inside that shadow. Its cost to the user is zero
        # seconds and zero dollars, and on three boards in four it finds nothing at all.
        current_step = _STEP_CAPTURE
        well_known_task = asyncio.ensure_future(do_collect_well_known(url))
        try:
            captured = await do_capture(
                url,
                on_live_view=_publish_live_view,
                on_live_view_closed=_publish_live_view_closed,
                on_request=_publish_request,
            )
        except CaptureError as exc:
            await _abandon(well_known_task)
            raise _Refusal(_STEP_CAPTURE, str(exc)) from exc
        except BaseException:
            # Every other exit from the capture — including the discovery task's own
            # 240 s cancellation — must not leave a pending task nobody awaits.
            await _abandon(well_known_task)
            raise
        # ``collect_well_known`` never raises, so this can only ever return evidence
        # (empty, on the common path). It has almost always finished already.
        well_known = await well_known_task
        if well_known.sources:
            logger.info(
                "well-known collector read %d document(s) for %s: %s",
                len(well_known.sources), url,
                ", ".join(f"{s.origin} ({s.note})" for s in well_known.sources),
            )

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
        # SOURCES 2a AND 6 — the DOCUMENT, as candidates. Zero network requests and zero
        # added wall clock: the served body was already fetched by the host pin and
        # thrown away, and the rendered DOM was already read for the link harvest. What
        # they cost is pipe bytes.
        #
        # They go on the END, after the pre-filter has ranked the XHRs, because a board
        # that publishes a real jobs feed must never have its answer crowded out by a
        # marketing page's ld+json. And only SERVED islands are here: an island that
        # exists only after hydration has no replay transport, so it may contribute ids
        # and never a recipe (:class:`~.sources.HtmlSource`).
        document = document_candidates(
            captured, _hostname_of(origin_url), captured.server_html_url or origin_url
        )
        if document:
            logger.info(
                "discovery derived %d document candidate(s) for %s: %s",
                len(document), url,
                ", ".join(
                    f"{c.html.op}({c.html.selector}) -> {c.record_count} record(s)"
                    for c in document if c.html is not None
                ),
            )
        # THE PRE-FILTER'S VERDICT ON EVERY ROW, published before any refusal below can
        # leave the function. The commonest refusal we serve is "none of the 14 JSON
        # requests this page made returned a list of job postings", and that sentence is
        # an assertion with no evidence unless the fourteen rows are sitting under it
        # saying 0 records each.
        #
        # Scored off the NETWORK candidates only: a document candidate has no row in the
        # network log to mark (``source_index`` is -1), and inventing one would put a
        # request the browser never made into the list the user is reading.
        scores = {c.source_index: c.record_count for c in candidates}
        ledger.score_requests(scores)
        candidates = candidates + document
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
        blocked = set(scores) - {c.source_index for c in public} - {-1}
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
                answers = await do_select(candidates, feedback=feedback)
            except NoJobsFeedError as exc:
                # The model looked at what is left and said none of it is jobs. Asking
                # again cannot change that, and the alternative — a schema with no
                # refusal branch — is what lets a leftover filter catalogue be stored
                # as the company's board. Stop here.
                #
                # BUT WHOSE "NO" IS IT? On round two the model is answering with OUR OWN
                # measured failure attached as feedback, so its no is often an echo of
                # that failure rather than a verdict on the bytes — and reporting the
                # filter step then blames the board for something we did. Measured on
                # ``jpmc.fa.oraclecloud.com``: the fan-out answered 6 of 6 YES, the
                # coverage floor refused every one of them at 25 records against a
                # published 7,181, round two re-asked with exactly that attached, the
                # model reasonably said no — and the user was told the page publishes no
                # jobs feed. FOUR unrelated boards wore that identical sentence for four
                # different reasons and sent two investigations down the wrong path.
                #
                # So when we already measured why the last candidate died, report THAT
                # step and THAT reason. The jobs-feed sentence survives only for the case
                # where it is literally true: nothing we tried ever failed, the model
                # simply read the captured requests and saw no jobs in them.
                logger.info("discovery found no jobs feed for %s: %s", url, exc)
                if last_error is not None:
                    raise _Refusal(last_step, last_error) from exc
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

            # THE REFEREE. Several arrays on one page can all be "a list of job
            # postings"; which one gets STORED is settled on measurements, never on the
            # model's own ranking. See :func:`_rank_answers`.
            ranked = _rank_answers(answers, candidates)
            logger.info(
                "discovery fan-out for %s: %d of %d candidate(s) answered yes, ranked %s",
                url, len(ranked), len(candidates),
                [candidates[a.candidate_index].url for a in ranked],
            )
            # The candidates that got as far as being TRIED and failed. Round two
            # re-asks exactly these, with what we measured attached — never the ones the
            # model already declined, because asking again cannot change a no.
            failed: list[int] = []

            for answer in ranked:
                selection = answer.selection
                assert selection is not None      # ``_rank_answers`` only ranks yeses
                current_step = _STEP_SYNTHESIZE
                try:
                    candidate = _rebind_to_selection(
                        candidates[answer.candidate_index], selection
                    )
                    # ...and if that bound ONE GROUP of a grouped payload, take the whole
                    # board instead. Before the acceptance ladder, because everything it
                    # measures — the page size, the ids to match, the coverage verdict —
                    # must be about the array we are actually going to store.
                    candidate, selection = _widen_to_union(
                        candidate, selection, _origin_of(origin_url)
                    )
                    # ...and if the model saw no paging parameter, look where it cannot:
                    # inside a composite query value. Rebound HERE, once, so the page-size
                    # ladder, the recipe, the coverage verdict and the round's feedback
                    # all reason about the same paging.
                    if selection.pagination is None:
                        derived = _composite_pagination(candidate)
                        if derived is None:
                            # ...and if the board never fetched a second page while we
                            # watched, seed one and PROVE it. See
                            # :func:`_seed_composite_offset`.
                            seeded = await _seed_composite_offset(
                                candidate, selection, link_context.probe
                            )
                            if seeded is not None:
                                candidate = seeded
                                derived = _composite_pagination(candidate)
                        if derived is not None:
                            selection = replace(selection, pagination=derived)
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
                # THE TIERS THIS CANDIDATE CAN BE REPLAYED ON, which is a property of where
                # its records CAME FROM. A document candidate has exactly one: ``http_html``,
                # over the plain GET the served bytes came out of. ``browser_fetch`` cannot
                # carry markup at all (``recipe_schema`` hard-requires ``extract_json_path``
                # there), so offering it would be an attempt that can only ever fail schema
                # validation.
                tiers: tuple[tuple[str, ReplayFn], ...] = (
                    (("http_html", run_http),) if candidate.html is not None
                    else (("http_json", run_http), ("browser_fetch", run_browser))
                )
                for transport, replay in tiers:
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
                sitemap: SitemapMatch | None = None
                if accepted is not None:
                    # THE CROSS-SOURCE CLAIM. The candidate came out of the JSON network
                    # list; the sitemap came from a URL that list does not contain and never
                    # will. Joining them here is the whole point of collecting a second
                    # source: a feed's 10 records against the board's own 15,660 published
                    # job pages is a disagreement that is pure ARITHMETIC, and arithmetic is
                    # something code can refuse on without asking anybody.
                    sitemap = _sitemap_evidence(well_known, candidate, selection, origin_url)
                    coverage = _coverage(
                        accepted[1], candidate, selection,
                        extra_claims=_sitemap_claims(sitemap),
                    )
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
                    # ...and, only now that we know what the replay actually reads, the
                    # sitemap may become the board's COMPLETENESS ORACLE. See
                    # :func:`_attach_sitemap_oracle` for the two conditions and for why they
                    # answer different questions.
                    script = _attach_sitemap_oracle(
                        script, sitemap, rows, candidate, selection, origin_url
                    )
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
                # THIS candidate cannot be replayed. Record what we measured about it
                # and move to the NEXT ONE THE MODEL SAID YES ABOUT — which the fan-out
                # makes a real fallback for the first time: before it, "the next
                # candidate" meant a second forced pick out of a list the model had
                # already ranked, and a forced pick of a leftover facet catalogue passes
                # the acceptance gate trivially (it proves the replay reads the SAME
                # array the browser saw, so a filter list overlaps itself 100%).
                # Measured on the TikTok capture: with the jobs POST dropped, discovery
                # stored ``…/job/filters`` and tracked "Engineering" and "Design" as the
                # company's job postings, forever, with a nightly harvest that would
                # never fail. Now a candidate is only ever tried because the model was
                # asked about IT and said yes about IT.
                feedback = _selection_feedback(last_error, selection, link_why)
                failed.append(answer.candidate_index)

            # The round is spent. ROUND TWO RE-ASKS EXACTLY THE CANDIDATES THAT FAILED
            # ACCEPTANCE, with the measured evidence attached — never the ones the model
            # declined, because asking again cannot change a no, and never a fresh list,
            # because the point of a second round is the evidence and not the re-roll.
            #
            # THIS IS THE FIX FOR A REAL GAP, KEPT. ``_MAX_SELECTION_ROUNDS`` fires on an
            # acceptance failure and not just a schema failure, and the old loop dropped
            # the failed candidate unconditionally — so a SINGLE-FEED board emptied the
            # list and ended before round two could happen. Atlassian and Jane Street
            # each publish exactly one jobs feed, so the boards that most needed a second
            # ask were precisely the ones that never got one.
            candidates = [
                replace(candidates[i], index=n) for n, i in enumerate(failed)
            ]

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
