"""REPLAY/HARVEST SIDE — the agent-free parent of the Stagehand subprocess (E7 pivot).

:func:`run_browser_agent` is the browser-agent analog of
:func:`api.services.recipe_runner.run_recipe`: it turns a stored
``transport='browser_agent'`` artifact into ``(rows, HarvestEvidence)`` that the
UNCHANGED Phase-2 gate/verdict consume. It:

1. re-validates the artifact (``max_pages ≤ 3`` bound re-checked on read, §4),
2. re-validates the ENTRY URL through ``url_guard`` (SSRF entry guard at replay time,
   §5 — the request-level CDP host-pin is NOT yet built; see ``_stagehand_main``),
3. spawns ``_stagehand_main`` OUT OF PROCESS (``stagehand`` never enters THIS
   process — that is the load-bearing agent-free boundary; ``run_browser_agent`` must
   NOT be reachable to an ``import stagehand``), parses its JSON report,
4. **re-asserts the bound + the stable-id proof (§3.4) EVERY run** — a row-index id
   (``"0-650"``), a cross-page id collision, or an over-budget page count all
   **RAISE** :class:`~api.services.recipe_runner.RecipeExecutionError` (the leaf task
   maps that to a FAILED run: writes nothing destructive, is NOT a miss). This is the
   contract that keeps a row-index id from EVER reaching the close path.

This module imports ONLY stdlib + ``httpx``-free helpers (``schema``, ``harvest_meta``,
``url_guard``, and ``recipe_runner`` for its error type / page-advance helper). It must
NEVER import ``stagehand``/``browserbase`` — the import-guard tests prove it, and it is
why ``_stagehand_main`` is a subprocess and not an in-process call.
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
from ..recipe_runner import RecipeExecutionError, _page_advance_ok
from ..url_guard import UrlGuardError, validate_public_url
from .schema import effective_max_pages, validate_browser_agent_script

logger = logging.getLogger(__name__)

# Subprocess wall-clock cap (§4). Mirrors the deleted observer's _SUBPROCESS_TIMEOUT_S.
_SUBPROCESS_TIMEOUT_S = 120.0

# A DOM row-index id the Stagehand extract emits when it reads a job's *position*
# instead of its detail-link href: "0-650", "3-42". These repeat across pages and
# collapse dedupe — the crux failure the validation surfaced (§3.4).
_ROW_INDEX_RE = re.compile(r"\d+-\d+")
_LONG_NUMERIC_RE = re.compile(r"\d{6,}")
_HAS_LETTER_RE = re.compile(r"[A-Za-z]")

RunSubprocess = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
UrlValidator = Callable[[str], Any]


def _looks_like_stable_id(value: str) -> bool:
    """True iff ``value`` looks like a REAL per-job id (href / slug / req-id), not a
    DOM row index. The stable-id proof (§3.4) rejects anything this returns False for.

    * ``"0-650"`` / ``"3-42"`` (``\\d+-\\d+``) → False: a Stagehand DOM position index.
    * contains ``/`` or starts with ``http`` → True: a detail-link href/path.
    * contains a letter (slug, ``R-123456``, ``eng-42abc``) and length ≥ 3 → True.
    * a bare number → True only if ≥ 6 digits (a plausible requisition id); a short
      bare integer (amazon ``"3363"``) is a DOM offset, not an id → False.
    """
    if _ROW_INDEX_RE.fullmatch(value):
        return False
    if "/" in value or value.startswith("http"):
        return True
    if _HAS_LETTER_RE.search(value):
        return len(value) >= 3
    if _LONG_NUMERIC_RE.fullmatch(value):
        return True
    return False


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
        if isinstance(parsed, dict) and "rows" in parsed:
            return parsed
    raise RecipeExecutionError("browser-agent subprocess produced no JSON report on stdout")


def _assert_stable_ids(page_id_sets: list[set[str]]) -> None:
    """The stable-id proof (§3.4): every id looks real AND pages are disjoint.

    RAISES :class:`RecipeExecutionError` on violation — reused by discovery (attempt
    N → retry the extract with a sharper instruction or REFUSE) AND by every nightly
    replay (RAISE → FAILED). A board that fails this NEVER reaches the close path.
    """
    seen: set[str] = set()
    for page in page_id_sets:
        for value in page:
            if not _looks_like_stable_id(value):
                raise RecipeExecutionError(
                    f"browser-agent id {value!r} is a DOM row-index / offset, not a "
                    "stable detail-link href/req-id — refusing to store or replay it "
                    "(a row-index id would churn or collapse dedupe every run, §3.4)"
                )
        collision = page & seen
        if collision:
            raise RecipeExecutionError(
                f"browser-agent ids repeat across pages ({sorted(collision)[:5]}) — the "
                "id_field is not stable/unique (pagination did not advance, or ids are "
                "row indices); refusing to store or replay it (§3.4)"
            )
        seen |= page


async def run_browser_agent(
    script: dict[str, Any],
    *,
    transport: str | None = None,
    oracle_kind: str | None = None,
    run_subprocess: RunSubprocess | None = None,
    validate_url: UrlValidator | None = None,
) -> tuple[list[dict[str, Any]], HarvestEvidence]:
    """Run ONE bounded browser-agent session for ``script`` → ``(rows, evidence)``.

    RAISES :class:`RecipeExecutionError` on ANY failure (subprocess crash/timeout,
    over-budget page count, a row-index id, a cross-page id collision, zero rows, or a
    post-dedup count below ``expected_min_jobs``) — never returns ``[]`` (the leaf
    task maps the raise to a FAILED run). ``run_subprocess`` / ``validate_url`` are
    injectable so tests run at $0 against a fake report and a no-op URL guard.
    """
    validate_browser_agent_script(script, transport=transport, oracle_kind=oracle_kind)
    (validate_url or _default_validate_url)(script["entry_url"])

    report = await (run_subprocess or _subprocess_run)(script)

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

    raw_page_id_sets = report.get("page_id_sets") or []
    if not isinstance(raw_page_id_sets, list) or len(raw_page_id_sets) != pages_fetched:
        raise RecipeExecutionError(
            "browser-agent report page_id_sets is missing or inconsistent with pages_fetched"
        )
    page_id_sets: list[set[str]] = [
        {str(v) for v in page} for page in raw_page_id_sets
    ]

    # THE CRUX — stable-id proof (§3.4). RAISES on a row-index id or a cross-page
    # collision, so a browser-agent board without a proven-stable id can never close.
    _assert_stable_ids(page_id_sets)

    id_field = script["id_field"]
    expected_min_jobs = int(script.get("expected_min_jobs") or 1)
    rows_raw = report.get("rows")
    if not isinstance(rows_raw, list):
        raise RecipeExecutionError("browser-agent report rows is missing or not a list")

    # Map to (id, title, …) rows and dedupe by the stable id (keep first — document
    # order), mirroring recipe_runner's contract so recipe_rows_to_job_listings + the
    # gate/verdict/upsert tail are byte-identical.
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows_raw:
        if not isinstance(row, dict):
            continue
        raw_id = row.get(id_field)
        title = row.get("title")
        if raw_id in (None, "") or title in (None, ""):
            continue  # map_records-style drop
        mapped = dict(row)
        mapped["id"] = str(raw_id)
        deduped.setdefault(mapped["id"], mapped)

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
