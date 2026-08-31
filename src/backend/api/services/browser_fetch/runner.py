"""REPLAY SIDE — the agent-free parent of the local-Chromium fetch subprocess (E7 Phase 3c).

:func:`run_browser_fetch` is the ``browser_fetch`` analog of
:func:`api.services.recipe_runner.run_recipe`: it turns a stored
``transport='browser_fetch'`` recipe into ``(rows, HarvestEvidence)`` that the
UNCHANGED Phase-2 gate consumes. A ``browser_fetch`` recipe is the SAME ``steps``
grammar ``http_json`` uses plus one required ``origin_url`` — the only difference is
WHO issues the request: a ``fetch()`` inside our own headless Chromium, on the board's
own origin, instead of ``httpx`` from the worker. That buys the boards that
origin-check / cookie-gate / sign an otherwise perfectly deterministic JSON API
(TikTok's ``search/job/posts`` 400s from httpx and 200s from ``lifeattiktok.com``),
for the price of our own CPU — no Browserbase hours, no LLM, no DOM parsing.

Order of operations, mirroring the capture side's ``network_capture.capture_board``
(same boundary, same reasons):

1. :func:`~api.services.recipe_runner.assert_no_agent_imports` FIRST — even though the
   browser runs out of process, a driver resident in THIS worker is a contamination
   proof regardless of who put it there;
2. validate-on-read (``validate_recipe`` with the ``company_scripts`` columns, so a
   JSONB-vs-column drift is caught on replay, not just at write time);
3. SSRF: ``url_guard.validate_public_url`` on BOTH ``origin_url`` and the captured
   fetch URL, BEFORE anything spawns (a blocked URL must cost zero Chromium);
4. spawn ``_browser_fetch_main`` OUT OF PROCESS — ``playwright`` never enters this
   process, the load-bearing agent-free boundary the AST guard proves;
5. re-assert the page bound on read, parse each raw body, and hand the payloads to
   ``recipe_runner.harvest_json_pages`` — the SAME in-band-error check, dig, mapping,
   dedupe, oracle and evidence build the httpx tier uses. Nothing about the
   RAISES-never-empty ladder is reimplemented here.

**RAISES, never returns ``[]``** (invariant #1): a non-2xx page, a non-JSON body, an
in-band error code, zero usable rows, a count under ``expected_min_jobs``, a child
that overran its page budget, a Chromium crash and a subprocess timeout are all
:class:`~api.services.recipe_runner.RecipeExecutionError`. The leaf task's narrow
``except`` turns that into a recorded FAILED run, which closes nothing and is not a
miss (invariant #2).

This module imports stdlib + ``httpx``-backed first-party helpers ONLY. It must NEVER
import ``playwright`` — that is why ``_browser_fetch_main`` is a subprocess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from ..guarded_client import guarded_sync_client
from ..harvest_meta import HarvestEvidence
from ..recipe_runner import (
    RecipeExecutionError,
    RecipePlan,
    assert_no_agent_imports,
    harvest_json_pages,
    parse_plan,
)
from ..recipe_schema import BROWSER_FETCH, BROWSER_FETCH_MAX_PAGES, validate_recipe
from ..url_guard import _DNS_EXECUTOR, UrlGuardError, validate_public_url

logger = logging.getLogger(__name__)

# Subprocess wall-clock cap. It MUST stay strictly BELOW the leaf task's
# ``_TASK_TIMEOUT_S`` (900s), and that ordering is the whole point, not a detail: if
# the task's guard fires first it CANCELS this coroutine, a ``CancelledError`` is not
# an ``asyncio.TimeoutError``, and the timeout branch below — the only place that
# kills the child — would never run. That is exactly the "Chromium parked on the
# Railway box" this constant exists to prevent, so 90 < 900 is load-bearing.
# (The ``finally`` in :func:`_subprocess_run` reaps on the cancellation path too; the
# ordering is what makes the FAILURE legible as a timeout instead of a task death.)
#
# This is the ONLY wall-clock bound on the whole sweep. The child's own budgets are
# PER-STEP (45s nav + 2.5s settle + 30s per in-page fetch), so at the 25-page ceiling
# its arithmetic worst case is ~800s; blowing 90s is a FAILED run, which closes
# nothing and is not a miss, so the cap — not the ceiling — is what bounds a wedged
# board. A recipe that legitimately needs more than 90s of paging is a recipe this
# tier cannot serve, and failing loudly is the correct answer to that.
_SUBPROCESS_TIMEOUT_S = 90.0

# How long to wait for a SIGKILLed child to actually die before giving up on reaping
# it ourselves. ``tini`` is PID 1 in the container precisely so an unreaped
# grandchild is still collected (see the Dockerfile's pthread-exhaustion note).
_REAP_TIMEOUT_S = 10.0

# Hard page ceiling the PARENT enforces on read, independent of what the recipe says
# and independent of the child's own identical ceiling. Two sides must agree for a
# run to be accepted (§ the bound, re-asserted on read).
#
# ALIASED to the schema's constant rather than restated: ``validate_recipe`` now
# REJECTS a browser_fetch recipe whose ``max_pages`` exceeds it (on write and on every
# read), so discovery can never author one and a drifted row FAILS loudly instead of
# being silently clamped down to a truncated sweep. Two copies of this number would
# drift, and the direction they drift in decides whether an over-budget board is a
# loud failure or a quiet partial harvest.
_MAX_PAGES_CEILING = BROWSER_FETCH_MAX_PAGES

RunSubprocess = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
UrlValidator = Callable[[str], Any]


# --------------------------------------------------------------------------
# plan → subprocess request
# --------------------------------------------------------------------------

def effective_max_pages(plan: RecipePlan) -> int:
    """``min(pagination.max_pages, ceiling)``; 1 when the recipe has no pagination."""
    pagination = plan.pagination
    if not isinstance(pagination, dict):
        return 1
    declared = pagination.get("max_pages")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        return 1
    return min(declared, _MAX_PAGES_CEILING)


def _child_pagination(plan: RecipePlan) -> dict[str, Any] | None:
    """Flatten the recipe's pagination step into the child's dumb ``{style, param, …}``.

    ``paginate_facet`` is rejected by ``validate_recipe`` for this transport; the raise
    here is the defence-in-depth copy, because a stored script that somehow drifted
    past the schema must FAIL loudly rather than quietly harvest one facet's worth of
    a board and look like a shrink.
    """
    pagination = plan.pagination
    if pagination is None:
        return None
    op = pagination["op"]
    style = {"paginate_offset": "offset", "paginate_page": "page"}.get(op)
    if style is None:
        raise RecipeExecutionError(
            f"browser_fetch does not support pagination op {op!r} — refusing to replay "
            "a script whose paging it cannot reproduce exactly; FAILED"
        )
    return {
        "style": style,
        "param": pagination["param"],
        "page_size": int(pagination["page_size"]),
        "max_pages": effective_max_pages(plan),
        "start_page": int(pagination.get("start_page", 1)),
        "window_cap": pagination.get("window_cap"),
    }


def _hostname(url: str) -> str:
    """Lowercased host of ``url``, or ``''``. Matches the child's own copy."""
    return (urlsplit(url).hostname or "").lower()


def build_subprocess_plan(script: dict[str, Any], plan: RecipePlan) -> dict[str, Any]:
    """The JSON the child reads on stdin. Deliberately NOT the recipe: the child gets
    only what it needs to issue the requests (D3 — the child is dumb), so extraction,
    shaping, dedupe and the oracle stay on this side of the boundary."""
    origin_url = script["origin_url"]
    fetch_url = plan.fetch["url"]
    return {
        "origin_url": origin_url,
        "method": plan.fetch.get("method", "GET"),
        "url": fetch_url,
        "headers": dict(plan.fetch.get("headers") or {}),
        "body": dict(plan.fetch.get("body") or {}),
        # HOW the POST body goes on the wire, forwarded verbatim because the child is
        # dumb and this is a property of the RECIPE. It is the one Stage-2 primitive
        # that had to cross this boundary: metacareers.com's jobs GraphQL answers 200
        # with 876 records to a form-encoded body and 400 to the same fields as JSON,
        # from inside its own origin — which is the only place it answers at all, so
        # ``browser_fetch`` is the transport that needs it most.
        "body_encoding": plan.fetch.get("body_encoding", "json"),
        "pagination": _child_pagination(plan),
        # The child counts records ONLY to know when to stop paging; the parent is
        # what turns an unresolvable path into a FAILED run.
        "records_path": plan.extraction["records_path"],
        # THE HOST-PIN. Exactly the two hosts this parent SSRF-validated below, so
        # the child can refuse the redirect hops Chromium would otherwise take on
        # its own — the same host-pin ``guarded_client.GuardedTransport`` gives the
        # httpx tier against the same stored recipes. Sorted so the plan handed to
        # the child is deterministic.
        "allowed_hosts": sorted({_hostname(origin_url), _hostname(fetch_url)} - {""}),
    }


# --------------------------------------------------------------------------
# SSRF guard + subprocess
# --------------------------------------------------------------------------

def _default_validate_url(url: str) -> None:
    """SSRF guard (raises :class:`RecipeExecutionError` on a private/blocked host, so a
    rejection honours RAISES-never-empty). Real DNS via ``url_guard``; its reason codes
    are an API contract and are quoted verbatim into the message."""
    try:
        validate_public_url(url)
    except UrlGuardError as exc:
        raise RecipeExecutionError(
            f"browser_fetch URL {url!r} blocked by the SSRF guard ({exc.reason}): {exc}"
        ) from exc


# Everything the child legitimately needs, and nothing else. It is an ALLOWLIST on
# purpose — see :func:`_child_env`.
_ENV_ALLOWLIST = (
    "PATH",                 # find the interpreter's own tooling
    "HOME",                 # where `playwright install` put ~/.cache/ms-playwright
    "TMPDIR", "TMP", "TEMP",  # Chromium's user-data-dir / crashpad scratch
    "LANG", "LC_ALL",       # locale-dependent text handling in the child
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR",
    "PYTHONUNBUFFERED",     # the Dockerfile sets it so stderr is line-flushed
    "SYSTEMROOT",           # Windows-only; harmless elsewhere, fatal to omit there
)


def _child_env() -> dict[str, str]:
    """The child's ENTIRE environment: an allowlist, NOT a copy of ours.

    ``dict(os.environ)`` would hand a Chromium launched with ``--no-sandbox`` — and
    pointed at an origin a stored, LLM-authored recipe chose — the worker's whole
    production credential set (``DATABASE_URL``, ``INTERNAL_API_KEY``,
    ``ANTHROPIC_API_KEY``, ``BROWSERBASE_API_KEY``), inherited straight into every
    renderer process. Unlike the capture child (which may be handed a Browserbase CDP
    URL) this one needs ZERO secrets, so the
    allowlist is short and the docstring below ("NO credentials are injected") is
    something the code actually enforces rather than merely asserts.

    ``PLAYWRIGHT_*`` passes through by prefix because the browser-path vars an image
    may set are not a fixed list; none of them is a secret.
    """
    env = {
        key: os.environ[key]
        for key in _ENV_ALLOWLIST
        if key in os.environ
    }
    env.update(
        {k: v for k, v in os.environ.items() if k.startswith("PLAYWRIGHT_")}
    )
    return env


async def _reap(proc: Any) -> None:
    """SIGKILL the child if it is still running, then WAIT for it — on EVERY path.

    ``kill()`` without the ``wait()`` leaves a zombie holding its pid and pipes, and
    no ``kill()`` at all leaves a live headless Chromium (hundreds of MB) on the
    Railway box plus a child blocked forever writing a report into a pipe whose
    reader is gone. Swallowing a cancellation here is deliberate: the SIGKILL is
    already delivered, ``tini`` collects what we could not, and re-raising would
    replace the real failure with a bookkeeping one.
    """
    if proc.returncode is not None:
        return
    try:
        proc.kill()
    except ProcessLookupError:      # it exited between the check and the kill
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_REAP_TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("browser_fetch subprocess did not exit after SIGKILL")


def _child_roots(module_file: str | Path) -> tuple["Path", "Path"]:
    """``(backend_root, repo_root)`` for the child's PYTHONPATH, in BOTH layouts.

    THE BUG THIS EXISTS TO PREVENT (production, 2026-08-31). A dev checkout puts this
    file at ``<repo>/src/backend/api/services/.../x.py``, so ``parents[3]`` is
    ``src/backend`` and the repo root that holds ``scripts/`` is two levels above it.
    The Docker image is FLAT — ``WORKDIR /app`` with ``COPY src/backend/api/ ./api/``
    and ``COPY scripts/ ./scripts/`` — so ``parents[3]`` is ``/app``, whose ONLY parent
    is ``/``. The old unconditional ``backend_root.parents[1]`` therefore raised
    ``IndexError: 1`` on every run in production while every local test passed, because
    the tests run in a checkout deep enough for the arithmetic to work.

    In Docker ``backend_root`` already holds ``scripts/``, so it IS the repo root.
    Mirrors the dev/docker split ``api.migrations`` has always made.
    """
    backend_root = Path(module_file).resolve().parents[3]
    repo_root = (
        backend_root.parents[1] if len(backend_root.parents) > 1 else backend_root
    )
    return backend_root, repo_root


async def _subprocess_run(subprocess_plan: dict[str, Any]) -> dict[str, Any]:
    """Spawn ``_browser_fetch_main`` and return its parsed JSON report.

    NO credentials are injected: this child ONLY ever drives a LOCAL Chromium (the
    Browserbase opt-in is discovery-time only), so it needs no API key and must never
    be handed one —
    :func:`_child_env` is what makes that true. The child imports ``playwright``;
    THIS parent never does — the boundary that keeps the replay worker agent-free.
    """
    backend_root, repo_root = _child_roots(__file__)
    env = _child_env()
    prior = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(backend_root), str(repo_root), prior) if p
    )

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "api.services.browser_fetch._browser_fetch_main",
        cwd=str(backend_root),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=json.dumps(subprocess_plan).encode("utf-8")),
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        raise RecipeExecutionError(
            f"browser_fetch subprocess timed out after {_SUBPROCESS_TIMEOUT_S}s"
        ) from exc
    finally:
        # NOT in the ``except`` — the leaf task's 120s ``wait_for`` cancels this
        # coroutine, and a ``CancelledError`` (a BaseException) skips every
        # ``except`` clause here. Reaping in the ``finally`` is what makes the
        # kill unconditional; without it the one path that actually strands a
        # Chromium is the one path that never killed it.
        await _reap(proc)
    if proc.returncode != 0:
        raise RecipeExecutionError(
            f"browser_fetch subprocess failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace')[:500]}"
        )
    return _parse_report(stdout.decode("utf-8", "replace"))


def _parse_report(stdout: str) -> dict[str, Any]:
    """Parse the report from stdout, tolerating stray log lines (Chromium is chatty)."""
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "pages" in parsed and "pages_fetched" in parsed:
            return parsed
    raise RecipeExecutionError("browser_fetch subprocess produced no JSON report on stdout")


# --------------------------------------------------------------------------
# report → payloads (the parent owns every judgement)
# --------------------------------------------------------------------------

def _payloads_from_report(
    report: dict[str, Any], max_pages: int
) -> tuple[list[Any], dict[str, str], bool, bool]:
    """Validate the report, re-assert THE BOUND, and parse each raw body.

    Returns ``(page_payloads, first_page_headers, terminated_cleanly, cap_hit)``.
    Every failure here RAISES — a report we cannot fully believe must be FAILED, never
    a short harvest that reads as "the board shrank".
    """
    pages_fetched = report.get("pages_fetched")
    if not isinstance(pages_fetched, int) or isinstance(pages_fetched, bool) or pages_fetched < 1:
        raise RecipeExecutionError(
            f"browser_fetch report pages_fetched={pages_fetched!r} is invalid"
        )
    # THE BOUND, re-asserted on read: the subprocess must never exceed it. The child
    # enforces the same ceiling; disagreement means the child is not the one we think.
    if pages_fetched > max_pages:
        raise RecipeExecutionError(
            f"browser_fetch fetched {pages_fetched} pages but the bound is {max_pages} "
            "(the subprocess ignored the page cap) — refusing this run"
        )
    raw_pages = report.get("pages")
    if not isinstance(raw_pages, list) or len(raw_pages) != pages_fetched:
        raise RecipeExecutionError(
            "browser_fetch report pages is missing or inconsistent with pages_fetched"
        )

    payloads: list[Any] = []
    first_headers: dict[str, str] = {}
    for index, entry in enumerate(raw_pages):
        if not isinstance(entry, dict):
            raise RecipeExecutionError(f"browser_fetch report page {index} is not an object")
        status = entry.get("status")
        text = entry.get("text")
        if not isinstance(status, int) or isinstance(status, bool):
            raise RecipeExecutionError(
                f"browser_fetch report page {index} has a non-integer status {status!r}"
            )
        if not (200 <= status < 300):
            raise RecipeExecutionError(
                f"HTTP {status} from the in-browser fetch on page {index} "
                f"(body starts: {str(text)[:180]!r})"
            )
        if not isinstance(text, str):
            raise RecipeExecutionError(
                f"browser_fetch report page {index} has a non-string body"
            )
        try:
            # strict=False mirrors the httpx tier: some boards embed raw control
            # bytes in descriptions and json.loads is strict about them by default.
            payloads.append(json.loads(text, strict=False))
        except Exception as exc:  # noqa: BLE001
            raise RecipeExecutionError(
                f"unparseable JSON from the in-browser fetch on page {index}: {exc} "
                f"(body starts: {text[:180]!r})"
            ) from exc
        if index == 0:
            headers = entry.get("headers")
            first_headers = (
                {str(k): str(v) for k, v in headers.items()}
                if isinstance(headers, dict) else {}
            )

    return payloads, first_headers, bool(report.get("terminated_cleanly")), bool(report.get("cap_hit"))


def _process(plan: RecipePlan, report: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
    """Parse the report and run the SHARED recipe machinery over its payloads.

    Sync on purpose: :func:`run_browser_fetch` calls it in a worker thread, because a
    big board's JSON parse is real CPU and the ``sitemap`` oracle does a blocking GET —
    neither belongs on the Procrastinate event loop.
    """
    payloads, first_headers, terminated_cleanly, cap_hit = _payloads_from_report(
        report, effective_max_pages(plan)
    )
    # The sitemap oracle is the only one that needs a network client, and a sitemap GET
    # needs no browser — so it rides the SAME SSRF-guarded sync client the httpx tier
    # uses. Every other oracle reads the payload/headers we already have.
    http: httpx.Client | None = None
    try:
        if plan.oracle.get("kind") == "sitemap":
            http = guarded_sync_client()
        return harvest_json_pages(
            plan, payloads,
            first_headers=first_headers,
            terminated_cleanly=terminated_cleanly,
            cap_hit=cap_hit,
            http=http,
        )
    finally:
        if http is not None:
            http.close()


# --------------------------------------------------------------------------
# public entry
# --------------------------------------------------------------------------

async def run_browser_fetch(
    script: dict[str, Any],
    *,
    transport: str | None = None,
    oracle_kind: str | None = None,
    run_subprocess: RunSubprocess | None = None,
    validate_url: UrlValidator | None = None,
) -> tuple[list[dict], HarvestEvidence]:
    """REPLAY one stored ``browser_fetch`` recipe → ``(rows, evidence)``.

    RAISES :class:`RecipeExecutionError` on ANY failure (the leaf task maps the raise
    to a FAILED run, which closes nothing). ``run_subprocess`` / ``validate_url`` are
    injectable so tests run at $0 against a fake report and a no-op URL guard — the
    same seam ``capture_board`` uses.
    """
    # FIRST, every call — the agent-free proof. The Chromium session runs OUT OF
    # PROCESS, so this raises only if a driver leaked into the worker some other way;
    # that is exactly the co-tenancy bug it exists to catch.
    assert_no_agent_imports()
    validate_recipe(script, transport=transport, oracle_kind=oracle_kind)
    if script.get("transport") != BROWSER_FETCH:
        # Reachable only when the caller passed transport=None (no column to compare
        # against). Running an http_json recipe through a browser would work and be
        # wrong: it would burn Chromium nightly for a board that needs none.
        raise RecipeExecutionError(
            f"run_browser_fetch got a {script.get('transport')!r} script — "
            f"only {BROWSER_FETCH!r} recipes replay in the browser; FAILED"
        )
    plan = parse_plan(script)

    # SSRF on BOTH user-influenced URLs, BEFORE anything spawns (invariant #4). The
    # origin is what Chromium navigates to; the fetch URL is what runs inside it. A
    # blocked one costs zero browser.
    #
    # OFF THE LOOP. ``validate_public_url`` is sync and does a blocking
    # ``getaddrinfo`` on a host a stored, LLM-authored recipe chose — url_guard
    # measured the loop ticking 0 times during a 1.0s lookup, and we share this
    # process with the Procrastinate worker, so a board with a blackholing resolver
    # would stall every in-flight ATS fetch AND the 120s task backstop meant to save
    # us. ``_DNS_EXECUTOR`` rather than ``asyncio.to_thread`` for the reason stated
    # at that constant: the loop's default pool is the one every outbound connection
    # in this process already shares. Sequential, so the two calls stay ordered.
    loop = asyncio.get_running_loop()
    check_url = validate_url or _default_validate_url
    await loop.run_in_executor(_DNS_EXECUTOR, check_url, script["origin_url"])
    await loop.run_in_executor(_DNS_EXECUTOR, check_url, plan.fetch["url"])

    subprocess_plan = build_subprocess_plan(script, plan)
    report = await (run_subprocess or _subprocess_run)(subprocess_plan)
    return await asyncio.to_thread(_process, plan, report)
