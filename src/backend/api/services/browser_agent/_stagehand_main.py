"""SUBPROCESS ENTRY — the ONLY module that imports ``stagehand`` (E7 pivot).

Runs ONE bounded Browserbase Stagehand session for a single browser-agent artifact
and prints a JSON report to stdout. It is spawned by
:func:`api.services.browser_agent.runner.run_browser_agent` via
``asyncio.create_subprocess_exec`` — NEVER imported in-process — so
``stagehand``/``browserbase`` never land in the shared Procrastinate worker's
``sys.modules`` and the replay path's ``assert_no_agent_imports`` guard stays
satisfied. This is exactly why it is a subprocess (mirrors the deleted
``services/discovery/_capture_main`` Playwright pattern).

The loop is the proven spike loop (``scripts/one_off/stagehand_spike/run_spike.py``):

    navigate(entry_url) → observe(pagination) → extract(schema)
                        → [act(next_action) → extract] × (max_pages - 1)

bounded by a FIXED ``for page in range(effective_max_pages(script))`` (≤ 3, §4) —
NOT ``sessions.execute()`` autonomous crawl. The report shape is::

    {rows, pages_fetched, terminated_cleanly, page_id_sets,
     expected_min_jobs, observed_actions, max_pages}

===========================================================================
SSRF — READ BEFORE FLIPPING ``browser_agent_enabled`` ON FOR UNTRUSTED USERS
===========================================================================
The REQUEST-LEVEL host-pin (CDP ``Fetch.requestPaused`` over ``session.data.cdp_url``,
§5) that aborts any in-page request whose host is not the pinned target is **NOT
implemented here**. v1 relies on two weaker layers:

  1. the add-time + replay-time ``url_guard.validate_public_url`` on the ENTRY URL
     (enforced in ``runner.run_browser_agent`` before this subprocess is spawned), and
  2. Browserbase ``allowedDomains=[entry_host]`` passed below as defence-in-depth —
     which restricts only MAIN-FRAME navigations, NOT iframe/XHR/subresource loads,
     and is bypassable via a proxy/translate service on an allowed domain.

Neither closes a page that fetches ``169.254.169.254`` (cloud metadata) or an
internal host via XHR. Therefore ``config.browser_agent_enabled`` — the real
per-transport kill-switch, ENFORCED in both the discovery add-flow AND the nightly
replay branch (``fetch_custom_company``) — MUST stay OFF by default and MUST NOT be
enabled for untrusted, arbitrary user URLs until the CDP pin lands. Credentials are
read from the environment and NEVER printed.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlparse

# The ONLY stagehand import in the whole backend, and it is in a child process.
from stagehand import Stagehand

# Wall-clock ceiling handed to Browserbase for the session itself (seconds). The
# parent ALSO enforces a subprocess timeout (~120s); this is the belt to that
# suspenders so a hung remote browser cannot bill indefinitely.
_SESSION_TIMEOUT_S = 90
_MODEL_NAME = "anthropic/claude-sonnet-4-5"
_DOM_SETTLE_TIMEOUT_MS = 15000
_SYSTEM_PROMPT = (
    "You read public job-board pages. Never crawl a whole board; work only on the "
    "page you are on. Extract the real per-job detail-link href as each job's id, "
    "never its row position on the page."
)


def _effective_max_pages(script: dict[str, Any]) -> int:
    """``min(pagination.max_pages, 3)``; 1 when there is no pagination block.

    Duplicated (not imported) from ``schema.effective_max_pages`` so this child has
    ZERO first-party import surface beyond stagehand + stdlib — it must never pull in
    the worker's service graph.
    """
    pagination = script.get("pagination")
    if not isinstance(pagination, dict):
        return 1
    declared = pagination.get("max_pages")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        return 1
    return min(declared, 3)


def _result(resp: Any) -> Any:
    """Stagehand responses expose ``.result``; fall back to a model dump."""
    if hasattr(resp, "result"):
        return resp.result
    if hasattr(resp, "model_dump"):
        try:
            return resp.model_dump().get("result")
        except Exception:  # noqa: BLE001 - best-effort accessor
            return None
    return resp


def _as_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "model_dump"):
        try:
            dumped = row.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:  # noqa: BLE001
            pass
    return {}


def _rows_from_extract(result: Any) -> list[dict[str, Any]]:
    """Pull the job-row list out of an extract result (schema wraps it as ``jobs``)."""
    if hasattr(result, "model_dump"):
        try:
            result = result.model_dump()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(result, dict):
        if isinstance(result.get("jobs"), list):
            return [_as_dict(r) for r in result["jobs"]]
        # Fall back to the first array value in the object.
        for value in result.values():
            if isinstance(value, list):
                return [_as_dict(r) for r in value]
        return []
    if isinstance(result, list):
        return [_as_dict(r) for r in result]
    return []


def _observed_actions(resp: Any) -> list[dict[str, Any]]:
    result = _result(resp)
    if not isinstance(result, list):
        return []
    out: list[dict[str, Any]] = []
    for item in result[:25]:
        out.append(
            {
                "description": str(getattr(item, "description", "") or ""),
                "selector": str(getattr(item, "selector", "") or ""),
                "method": str(getattr(item, "method", "") or ""),
            }
        )
    return out


def _act_succeeded(resp: Any) -> bool:
    result = _result(resp)
    success = getattr(result, "success", None)
    if success is None and isinstance(result, dict):
        success = result.get("success")
    return bool(success)


def _id_list(rows: list[dict[str, Any]], id_field: str) -> list[str]:
    ids: list[str] = []
    for row in rows:
        value = row.get(id_field)
        if value not in (None, ""):
            ids.append(str(value))
    return ids


def run_session(script: dict[str, Any]) -> dict[str, Any]:
    """Drive the bounded session and return the report dict (no printing)."""
    bb_key = os.environ.get("BROWSERBASE_API_KEY")
    bb_project = os.environ.get("BROWSERBASE_PROJECT_ID")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not (bb_key and bb_project and anthropic_key):
        raise RuntimeError("missing BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID / ANTHROPIC_API_KEY")

    entry_url = script["entry_url"]
    entry_host = urlparse(entry_url).hostname or ""
    id_field = script["id_field"]
    extract = script["extract"]
    instruction = extract["instruction"]
    schema = extract["schema"]
    pagination = script.get("pagination") if isinstance(script.get("pagination"), dict) else None
    next_action = pagination["next_action"] if pagination else None
    max_pages = _effective_max_pages(script)

    pages_rows: list[list[dict[str, Any]]] = []
    page_id_sets: list[list[str]] = []
    observed_actions: list[dict[str, Any]] = []
    reached_page_budget = False

    with Stagehand(
        server="remote",
        browserbase_api_key=bb_key,
        browserbase_project_id=bb_project,
        model_api_key=anthropic_key,
    ) as client:
        started = client.sessions.start(
            model_name=_MODEL_NAME,
            browser={"type": "browserbase"},
            dom_settle_timeout_ms=_DOM_SETTLE_TIMEOUT_MS,
            self_heal=True,
            system_prompt=_SYSTEM_PROMPT,
            # ``allowedDomains`` is an intentional extra key not in the SDK TypedDict;
            # Stainless forwards unknown keys to the Browserbase create-session API
            # (verified), so this is defence-in-depth ONLY (main-frame navigations; see
            # the SSRF banner at the top of this file), NOT the request-level control.
            browserbase_session_create_params={  # type: ignore[arg-type]
                "timeout": _SESSION_TIMEOUT_S,  # session wall-clock cap (documented field)
                "allowedDomains": [entry_host] if entry_host else [],
            },
        )
        sid = getattr(started, "id", None)
        if sid is None:
            data = _result(started)
            sid = data.get("id") if isinstance(data, dict) else None
        if not sid:
            raise RuntimeError("stagehand session did not return a session id")

        try:
            client.sessions.navigate(sid, url=entry_url)
            observed_actions = _observed_actions(
                client.sessions.observe(
                    sid,
                    instruction="find the job posting rows and any next-page pagination control",
                )
            )

            for page_idx in range(max_pages):
                rows = _rows_from_extract(
                    _result(client.sessions.extract(sid, instruction=instruction, schema=schema))
                )
                pages_rows.append(rows)
                page_id_sets.append(_id_list(rows, id_field))

                if pagination is None:
                    break  # single page by design → clean terminus
                if page_idx == max_pages - 1:
                    reached_page_budget = True
                    break
                # A page shorter than the first is a natural terminus (clean stop).
                if len(rows) < len(pages_rows[0]):
                    break
                if not _act_succeeded(
                    client.sessions.act(sid, input=str(next_action))
                ):
                    break  # no/failed next control → natural terminus (clean)
        finally:
            try:
                client.sessions.end(sid)
            except Exception:  # noqa: BLE001 - end is best-effort cleanup
                pass

    # terminated_cleanly (§3.3): a single page is the whole board; a paginated run
    # is clean unless it exhausted the page budget with a still-FULL final page
    # (which implies more pages remain, so completeness is unproven → UNVERIFIED).
    if reached_page_budget and len(pages_rows) > 1:
        terminated_cleanly = len(pages_rows[-1]) < len(pages_rows[0])
    else:
        terminated_cleanly = True

    all_rows: list[dict[str, Any]] = [row for page in pages_rows for row in page]
    return {
        "rows": all_rows,
        "pages_fetched": len(pages_rows),
        "terminated_cleanly": terminated_cleanly,
        "page_id_sets": page_id_sets,
        "expected_min_jobs": int(script.get("expected_min_jobs") or 1),
        "observed_actions": observed_actions,
        "max_pages": max_pages,
    }


def main() -> None:
    raw = sys.stdin.read()
    try:
        script = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid script JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        report = run_session(script)
    except Exception as exc:  # noqa: BLE001 - surface as rc!=0; parent RAISES → FAILED
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    # The report is the SOLE stdout payload; the parent parses the last JSON line.
    sys.stdout.write("\n" + json.dumps(report) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
