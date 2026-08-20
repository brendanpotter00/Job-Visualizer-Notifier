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

Order of operations, mirroring ``browser_agent.runner.run_browser_agent``:

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
from ..recipe_schema import BROWSER_FETCH, validate_recipe
from ..url_guard import UrlGuardError, validate_public_url

logger = logging.getLogger(__name__)

# Subprocess wall-clock cap. Larger than the browser-agent's 120s because this child
# pays a cold Chromium launch AND up to ``max_pages`` sequential in-page fetches,
# and smaller than the leaf task's own 120s guard would allow it to matter — the
# task timeout fires first on a truly wedged run; this one exists so a hung page
# cannot leave a Chromium parked on the Railway box.
_SUBPROCESS_TIMEOUT_S = 180.0

# Hard page ceiling the PARENT enforces on read, independent of what the recipe says
# and independent of the child's own identical ceiling. Two sides must agree for a
# run to be accepted (§ the bound, re-asserted on read).
_MAX_PAGES_CEILING = 25

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


def build_subprocess_plan(script: dict[str, Any], plan: RecipePlan) -> dict[str, Any]:
    """The JSON the child reads on stdin. Deliberately NOT the recipe: the child gets
    only what it needs to issue the requests (D3 — the child is dumb), so extraction,
    shaping, dedupe and the oracle stay on this side of the boundary."""
    return {
        "origin_url": script["origin_url"],
        "method": plan.fetch.get("method", "GET"),
        "url": plan.fetch["url"],
        "headers": dict(plan.fetch.get("headers") or {}),
        "body": dict(plan.fetch.get("body") or {}),
        "pagination": _child_pagination(plan),
        # The child counts records ONLY to know when to stop paging; the parent is
        # what turns an unresolvable path into a FAILED run.
        "records_path": plan.extraction["records_path"],
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


async def _subprocess_run(subprocess_plan: dict[str, Any]) -> dict[str, Any]:
    """Spawn ``_browser_fetch_main`` and return its parsed JSON report.

    NO credentials are injected: this child drives a LOCAL Chromium, so unlike the
    Browserbase/Stagehand child it needs no API key and must never be handed one. The
    child imports ``playwright``; THIS parent never does — the boundary that keeps the
    replay worker agent-free.
    """
    backend_root = Path(__file__).resolve().parents[3]  # src/backend
    repo_root = backend_root.parents[1]                 # repo root (holds scripts/)
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
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
        proc.kill()
        raise RecipeExecutionError(
            f"browser_fetch subprocess timed out after {_SUBPROCESS_TIMEOUT_S}s"
        ) from exc
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
    same seam ``run_browser_agent`` uses.
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
    check_url = validate_url or _default_validate_url
    check_url(script["origin_url"])
    check_url(plan.fetch["url"])

    subprocess_plan = build_subprocess_plan(script, plan)
    report = await (run_subprocess or _subprocess_run)(subprocess_plan)
    return await asyncio.to_thread(_process, plan, report)
