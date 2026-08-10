"""REPLAY/HARVEST SIDE — the agent-free parent of the Stagehand subprocess (E7 pivot).

:func:`run_browser_agent` is the browser-agent analog of
:func:`api.services.recipe_runner.run_recipe`: it turns a stored
``transport='browser_agent'`` artifact into ``(rows, HarvestEvidence)`` that the
UNCHANGED Phase-2 gate/verdict consume. It:

1. re-validates the artifact (``max_pages ≤ 3`` bound re-checked on read, §4),
2. re-validates the ENTRY URL through ``url_guard`` (SSRF entry guard at replay time,
   §5 — the request-level CDP host-pin is NOT yet built; see ``_stagehand_main``),
3. spawns ``_stagehand_main`` OUT OF PROCESS (``stagehand`` never enters THIS
   process — the load-bearing agent-free boundary), parses its ``page_rows`` report,
4. **re-asserts the bound + the stable-id proof (§3.4) EVERY run**, keyed on the
   STORED ``id_field``.

**ID-FIELD SELECTION (the crux, §3.4 + href-less boards).** Some boards (YC company
pages) render job rows as click-interactive divs with NO per-job ``<a href>``, so the
extract returns element-refs (``"0-650"``) for ``url`` — which the URL-shaped id check
correctly rejects. But their TITLES are distinct + stable. So discovery SELECTS the
``id_field`` from the extracted rows in priority order and STORES it:

* ``url`` — iff every row has a URL-shaped, distinct url;
* else ``title`` — iff titles are all non-empty, distinct, and none is an element-ref
  (``\\d+-\\d+``) / bare short int;
* else ``title|location`` — iff that composite tuple is distinct (titles still stable);
* else REFUSE (no stable id).

Replay reads the STORED ``id_field`` and builds the dedupe key from it, re-asserting
stability + cross-page disjointness. A non-stable id RAISES
:class:`~api.services.recipe_runner.RecipeExecutionError` (→ FAILED, never a wrong
close). The ``self_consistent`` churn guard in ``fetch_custom_company`` is the
across-run backstop for any chosen id_field.

This module imports ONLY stdlib + ``httpx``-free helpers. It must NEVER import
``stagehand``/``browserbase`` — the import-guard tests prove it, which is why
``_stagehand_main`` is a subprocess and not an in-process call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..harvest_meta import HarvestEvidence
from ..recipe_runner import RecipeExecutionError, _page_advance_ok, assert_no_agent_imports
from ..url_guard import UrlGuardError, validate_public_url
from .schema import (
    BROWSER_AGENT_ID_FIELDS,
    effective_max_pages,
    validate_browser_agent_script,
)

logger = logging.getLogger(__name__)

# Subprocess wall-clock cap (§4). Mirrors the deleted observer's _SUBPROCESS_TIMEOUT_S.
_SUBPROCESS_TIMEOUT_S = 120.0

# A Stagehand element-ref / DOM position ("0-650", "3-42") or a bare short integer
# ("3363") — a title/url shaped like either is NOT a stable per-job id (§3.4).
_ELEMENT_REF_RE = re.compile(r"\d+-\d+")
_SHORT_INT_RE = re.compile(r"\d{1,6}")
_HAS_LETTER_RE = re.compile(r"[A-Za-z]")

RunSubprocess = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
UrlValidator = Callable[[str], Any]


# --------------------------------------------------------------------------
# id-field stability predicates (id-field-AWARE, §3.4)
# --------------------------------------------------------------------------

def _is_element_ref_or_short_int(value: str) -> bool:
    return bool(_ELEMENT_REF_RE.fullmatch(value)) or bool(_SHORT_INT_RE.fullmatch(value))


def _url_looks_stable(url: str) -> bool:
    """A URL/path-shaped detail-link href (absolute ``http…`` or a leading-slash path).

    Deliberately strict: rejects element-refs (``"0-650"``), bare offsets (``"3363"``),
    and churning letter-slugs / nonces (``"job-1"``) that would close live jobs after
    the self_consistent streak."""
    return url.startswith("http") or "/" in url


def _title_looks_stable(title: str) -> bool:
    """A title is a usable stable id iff it has letters, is length ≥ 3, and is NOT an
    element-ref / bare short int (so a title accidentally set to ``"0-650"`` is rejected)."""
    return (
        bool(_HAS_LETTER_RE.search(title))
        and len(title) >= 3
        and not _is_element_ref_or_short_int(title)
    )


def _compose_id(row: dict[str, Any], id_field: str) -> str | None:
    """The dedupe/close key for ``row`` under ``id_field``. ``None`` when the id
    component is empty (the row is dropped, map_records-style)."""
    if id_field == "url":
        value = row.get("url")
        return str(value) if value not in (None, "") else None
    title = row.get("title")
    if title in (None, ""):
        return None
    title_str = str(title)
    if id_field == "title":
        return title_str
    # title|location composite
    location = row.get("location")
    location_str = "" if location in (None, "") else str(location)
    return f"{title_str}|{location_str}"


def _id_is_stable(row: dict[str, Any], id_field: str) -> bool:
    """Whether ``row``'s id under ``id_field`` is stable. For ``url`` the url must be
    URL-shaped; for ``title`` / ``title|location`` the TITLE must be stable (location
    is not constrained — it only disambiguates duplicate titles)."""
    if id_field == "url":
        value = row.get("url")
        return value not in (None, "") and _url_looks_stable(str(value))
    title = row.get("title")
    return title not in (None, "") and _title_looks_stable(str(title))


def _all_stable_and_distinct(rows: list[dict[str, Any]], id_field: str) -> bool:
    """Every row yields a stable, present id under ``id_field`` AND they are distinct."""
    ids: list[str] = []
    for row in rows:
        if not _id_is_stable(row, id_field):
            return False
        composed = _compose_id(row, id_field)
        if composed is None:
            return False
        ids.append(composed)
    return len(set(ids)) == len(ids)


def select_id_field(rows: list[dict[str, Any]]) -> str:
    """Pick the ``id_field`` for a board from its extracted rows (§3.4). Priority:
    ``url`` → ``title`` → ``title|location`` → REFUSE. Raises
    :class:`RecipeExecutionError` when no candidate is stable + distinct."""
    for candidate in BROWSER_AGENT_ID_FIELDS:
        if _all_stable_and_distinct(rows, candidate):
            return candidate
    raise RecipeExecutionError(
        "browser-agent extract yielded no stable id field — url values are "
        "element-refs / non-URLs and title(+location) is not distinct/stable; REFUSE "
        "(no per-job key to dedupe or close on, §3.4)"
    )


def _assert_ids_stable_and_disjoint(
    page_rows: list[list[dict[str, Any]]], id_field: str
) -> list[set[str]]:
    """Build per-page id sets for ``id_field``, RAISING on a non-stable id or a
    cross-page collision (§3.4). Returns the id sets for the page-advance signal."""
    seen: set[str] = set()
    page_id_sets: list[set[str]] = []
    for page in page_rows:
        ids: set[str] = set()
        for row in page:
            composed = _compose_id(row, id_field)
            if composed is None:
                continue
            if not _id_is_stable(row, id_field):
                raise RecipeExecutionError(
                    f"browser-agent {id_field} id {composed!r} is not stable "
                    "(element-ref / non-URL / bare int) — refusing to store or replay "
                    "it; it would churn or collapse dedupe and wrongly close jobs (§3.4)"
                )
            ids.add(composed)
        collision = ids & seen
        if collision:
            raise RecipeExecutionError(
                f"browser-agent ids repeat across pages ({sorted(collision)[:5]}) — the "
                f"{id_field} id is not unique across pages (pagination did not advance, "
                "or the id churns); refusing to store or replay it (§3.4)"
            )
        page_id_sets.append(ids)
        seen |= ids
    return page_id_sets


# --------------------------------------------------------------------------
# entry-URL SSRF guard + subprocess
# --------------------------------------------------------------------------

def _default_validate_url(url: str) -> None:
    """Entry-URL SSRF guard (raises :class:`RecipeExecutionError` on a private/blocked
    host, honouring the RAISES-never-empty contract). Real DNS via ``url_guard``."""
    try:
        validate_public_url(url)
    except UrlGuardError as exc:
        raise RecipeExecutionError(
            f"browser-agent entry URL {url!r} blocked by the SSRF guard "
            f"({exc.reason}): {exc}"
        ) from exc


async def _subprocess_run(script: dict[str, Any]) -> dict[str, Any]:
    """Spawn ``_stagehand_main`` and return its parsed JSON report.

    Credentials are injected via the child ENV (never argv, never logged). The child
    imports ``stagehand``; THIS parent never does — the boundary that keeps the
    replay worker agent-free.
    """
    from ...config import settings

    backend_root = Path(__file__).resolve().parents[3]  # src/backend
    repo_root = backend_root.parents[1]                 # repo root (holds scripts/)
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(backend_root), str(repo_root), prior) if p
    )
    # Pass credentials to the child through env (from settings, which loads .env.local).
    if settings.browserbase_api_key:
        env["BROWSERBASE_API_KEY"] = settings.browserbase_api_key
    if settings.browserbase_project_id:
        env["BROWSERBASE_PROJECT_ID"] = settings.browserbase_project_id
    if settings.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "api.services.browser_agent._stagehand_main",
        cwd=str(backend_root),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=json.dumps(script).encode("utf-8")),
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise RecipeExecutionError(
            f"browser-agent subprocess timed out after {_SUBPROCESS_TIMEOUT_S}s"
        ) from exc
    if proc.returncode != 0:
        raise RecipeExecutionError(
            f"browser-agent subprocess failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace')[:500]}"
        )
    return _parse_report(stdout.decode("utf-8", "replace"))


def _parse_report(stdout: str) -> dict[str, Any]:
    """Parse the report from stdout, tolerating stray log lines (Stagehand may log)."""
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "page_rows" in parsed:
            return parsed
    raise RecipeExecutionError("browser-agent subprocess produced no JSON report on stdout")


# --------------------------------------------------------------------------
# shared processing
# --------------------------------------------------------------------------

def _extract_page_rows(
    report: dict[str, Any], script: dict[str, Any]
) -> tuple[list[list[dict[str, Any]]], int]:
    """Validate the bound (§4) and return the per-page row lists + ``pages_fetched``."""
    max_pages = effective_max_pages(script)
    pages_fetched = report.get("pages_fetched")
    if not isinstance(pages_fetched, int) or pages_fetched < 1:
        raise RecipeExecutionError(f"browser-agent report pages_fetched={pages_fetched!r} is invalid")
    # THE BOUND, re-asserted on read (§4): the subprocess must never exceed it.
    if pages_fetched > max_pages:
        raise RecipeExecutionError(
            f"browser-agent fetched {pages_fetched} pages but the bound is {max_pages} "
            "(the subprocess ignored the page cap) — refusing this run"
        )
    raw = report.get("page_rows")
    if not isinstance(raw, list) or len(raw) != pages_fetched:
        raise RecipeExecutionError(
            "browser-agent report page_rows is missing or inconsistent with pages_fetched"
        )
    page_rows: list[list[dict[str, Any]]] = []
    for page in raw:
        if not isinstance(page, list):
            raise RecipeExecutionError("browser-agent report page_rows entry is not a list")
        page_rows.append([r for r in page if isinstance(r, dict)])
    return page_rows, pages_fetched


def _process(
    report: dict[str, Any],
    page_rows: list[list[dict[str, Any]]],
    pages_fetched: int,
    script: dict[str, Any],
    id_field: str,
) -> tuple[list[dict[str, Any]], HarvestEvidence]:
    """Assert stability + disjointness, map/dedupe rows, and build evidence."""
    page_id_sets = _assert_ids_stable_and_disjoint(page_rows, id_field)

    expected_min_jobs = int(script.get("expected_min_jobs") or 1)
    entry_url = script["entry_url"]
    deduped: dict[str, dict[str, Any]] = {}
    for page in page_rows:
        for row in page:
            composed = _compose_id(row, id_field)
            title = row.get("title")
            if composed is None or title in (None, ""):
                continue  # map_records-style drop
            mapped = dict(row)
            mapped["id"] = composed
            # A href-less board's url is an element-ref → useless as a link. Fall back
            # to the board entry_url so the job at least links to the careers page; a
            # real URL is kept as-is. (Never store an element-ref as a job url.)
            url_value = mapped.get("url")
            if not (isinstance(url_value, str) and _url_looks_stable(url_value)):
                mapped["url"] = entry_url
            deduped.setdefault(composed, mapped)

    rows = list(deduped.values())
    if not rows:
        raise RecipeExecutionError(
            "browser-agent produced zero usable rows — treated as FAILED, never 'no jobs today'"
        )
    if len(rows) < expected_min_jobs:
        raise RecipeExecutionError(
            f"browser-agent produced {len(rows)} rows, below expected_min_jobs="
            f"{expected_min_jobs} — refusing to report a partial board"
        )

    evidence = HarvestEvidence(
        declared_total=None,                       # self_consistent: no trusted total
        cap_hit=False,                             # no vendor cap; the bound rides terminated_cleanly
        terminated_cleanly=bool(report.get("terminated_cleanly")),
        page_advance_ok=_page_advance_ok(page_id_sets),
        pages_fetched=pages_fetched,
        transport_ok=True,
    )
    return rows, evidence


# --------------------------------------------------------------------------
# public entries — REPLAY (stored id_field) and DISCOVERY (selects id_field)
# --------------------------------------------------------------------------

async def run_browser_agent(
    script: dict[str, Any],
    *,
    transport: str | None = None,
    oracle_kind: str | None = None,
    run_subprocess: RunSubprocess | None = None,
    validate_url: UrlValidator | None = None,
) -> tuple[list[dict[str, Any]], HarvestEvidence]:
    """REPLAY one bounded browser-agent session using the STORED ``id_field`` →
    ``(rows, evidence)``. RAISES :class:`RecipeExecutionError` on ANY failure (the leaf
    task maps the raise to a FAILED run). ``run_subprocess`` / ``validate_url`` are
    injectable so tests run at $0 against a fake report and a no-op URL guard.
    """
    # FIRST, every call — the agent-free proof (mirrors ``run_recipe``). Even though
    # the Stagehand session runs OUT OF PROCESS, this raises if a browser/agent driver
    # ever leaked into THIS worker, so the invariant holds regardless of co-tenancy.
    assert_no_agent_imports()
    validate_browser_agent_script(script, transport=transport, oracle_kind=oracle_kind)
    (validate_url or _default_validate_url)(script["entry_url"])

    report = await (run_subprocess or _subprocess_run)(script)
    page_rows, pages_fetched = _extract_page_rows(report, script)
    return _process(report, page_rows, pages_fetched, script, script["id_field"])


async def run_browser_agent_selecting(
    script: dict[str, Any],
    *,
    transport: str | None = None,
    oracle_kind: str | None = None,
    run_subprocess: RunSubprocess | None = None,
    validate_url: UrlValidator | None = None,
) -> tuple[list[dict[str, Any]], HarvestEvidence, str]:
    """DISCOVERY variant — SELECTS the ``id_field`` from the extracted rows (ignoring
    the artifact's placeholder), then processes with it. Returns
    ``(rows, evidence, chosen_id_field)`` so discovery can STORE the choice.
    """
    assert_no_agent_imports()
    validate_browser_agent_script(script, transport=transport, oracle_kind=oracle_kind)
    (validate_url or _default_validate_url)(script["entry_url"])

    report = await (run_subprocess or _subprocess_run)(script)
    page_rows, pages_fetched = _extract_page_rows(report, script)
    flat = [row for page in page_rows for row in page]
    id_field = select_id_field(flat)
    rows, evidence = _process(report, page_rows, pages_fetched, script, id_field)
    return rows, evidence, id_field
