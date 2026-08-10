"""DISCOVERY OBSERVER — the agent's eyes on a careers page (E7 Phase 3b).

Ported from ``scripts/one_off/recipe_spike/capture.py``. Two halves:

* **Pure evidence-scoring** (``score_object`` / ``find_record_arrays`` /
  ``find_counts`` / ``scan_embedded_json`` / ``sketch_dom_repetition`` /
  ``build_report``) — no browser, no network. Testable in isolation and imported
  by the subprocess entrypoint (:mod:`._capture_main`).
* **``observe(url)``** — drives a **local headless Chromium OUT OF PROCESS** (a
  child ``python -m api.services.discovery._capture_main`` run), so ``playwright``
  never lands in *this* process's ``sys.modules``. That is what lets the shared
  Procrastinate worker host discovery AND the agent-free replay leaf task without
  the replay path's runtime guard (``recipe_runner.assert_no_agent_imports``)
  tripping on a resident browser driver.

The browser is injectable (``observe(url, capture_fn=...)``) so tests pass a
fixture observation and never touch a live site.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

# Keys that suggest an object is a job posting. Scored case-insensitively.
JOB_KEY_HINTS: dict[str, int] = {
    "title": 3, "job_title": 3, "jobTitle": 3, "name": 1, "position": 2,
    "location": 2, "locations": 2, "city": 1, "office": 1, "workplace": 1,
    "id": 1, "job_id": 2, "jobId": 2, "requisition": 3, "req_id": 3,
    "url": 1, "absolute_url": 2, "apply_url": 2, "job_path": 2, "externalPath": 2,
    "department": 1, "team": 1, "category": 1,
    "posted": 2, "posted_date": 3, "postedOn": 3, "created_at": 2, "updated_at": 1,
}

# Cap the compact report so a giant page can't balloon LLM token spend (§6 cost
# controls). Raw sample bodies are truncated field-by-field; this is the last
# backstop applied to the whole serialized report.
_MAX_REPORT_BYTES = 200_000
_SUBPROCESS_TIMEOUT_S = 120.0


def score_object(obj: dict[str, Any]) -> int:
    score = 0
    lowered = {str(k).lower() for k in obj}
    for hint, weight in JOB_KEY_HINTS.items():
        if hint.lower() in lowered:
            score += weight
    return score


def _truncate(value: Any, limit: int = 120) -> Any:
    if isinstance(value, str):
        return value[:limit] + ("…" if len(value) > limit else "")
    if isinstance(value, (list, dict)):
        text = json.dumps(value)[:limit]
        return text + "…"
    return value


def find_record_arrays(
    payload: Any, path: str = "", out: list[dict] | None = None, depth: int = 0
) -> list[dict]:
    """Walk a payload and report every array-of-objects with a job-like shape."""
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(payload, list):
        objs = [item for item in payload[:5] if isinstance(item, dict)]
        if objs:
            score = max(score_object(o) for o in objs)
            if score >= 4:
                out.append({
                    "path": path,
                    "count": len(payload),
                    "job_score": score,
                    "sample_keys": sorted(objs[0].keys())[:30],
                    "sample": {k: _truncate(v) for k, v in list(objs[0].items())[:12]},
                })
        for index, item in enumerate(payload[:3]):
            find_record_arrays(item, f"{path}.{index}" if path else str(index), out, depth + 1)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            find_record_arrays(value, f"{path}.{key}" if path else str(key), out, depth + 1)
    return out


def find_counts(payload: Any, depth: int = 0) -> dict[str, int]:
    """Harvest scalar *count* fields — completeness-oracle candidates."""
    found: dict[str, int] = {}
    if depth > 6:
        return found
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if isinstance(value, int) and not isinstance(value, bool) and (
                "count" in lowered or lowered in ("hits", "total", "totalcount", "numfound")
            ):
                found[key] = value
            elif isinstance(value, (dict, list)):
                found.update(find_counts(value, depth + 1))
    elif isinstance(payload, list):
        for item in payload[:3]:
            found.update(find_counts(item, depth + 1))
    return found


def scan_embedded_json(html: str) -> list[dict]:
    """Find JSON islands in the HTML (ld+json, __NEXT_DATA__, data-page, etc.)."""
    results: list[dict] = []
    patterns = [
        ("ld+json", r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>'),
        ("next-data", r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>'),
        ("application/json", r'<script[^>]+type="application/json"[^>]*>(.*?)</script>'),
    ]
    for label, pattern in patterns:
        for index, match in enumerate(re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)):
            blob = match.group(1).strip()
            if len(blob) < 40:
                continue
            try:
                payload = json.loads(blob, strict=False)
            except Exception:  # noqa: BLE001 - evidence, not control flow
                continue
            arrays = find_record_arrays(payload)
            arrays.sort(key=lambda a: (a["job_score"], a["count"]), reverse=True)
            is_job_posting = '"JobPosting"' in blob
            if arrays or is_job_posting:
                results.append({
                    "kind": label,
                    "index": index,
                    "is_job_posting_ld": is_job_posting,
                    "record_arrays": arrays[:3],
                })
            if len(results) >= 6:
                return results
    return results


def sketch_dom_repetition(html: str) -> list[dict]:
    """Cheap signal for server-rendered lists: most-repeated class attributes."""
    classes = re.findall(r'class="([^"]{3,120})"', html)
    counts: dict[str, int] = {}
    for value in classes:
        counts[value.strip()] = counts.get(value.strip(), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [{"class": name, "occurrences": n} for name, n in ranked[:15] if n >= 3]


def build_report(
    *,
    entry_url: str,
    page_title: str,
    nav_error: str | None,
    wall_seconds: float,
    responses: list[dict],
    html: str,
) -> dict[str, Any]:
    """Turn raw captured network responses + rendered HTML into the compact
    evidence report the author reads. Pure — no browser, no network.

    Each ``responses`` entry is ``{method, url, status, content_type,
    resource_type, body?}`` where ``body`` is the already-parsed JSON payload for
    JSON responses (or absent). This shape is what :mod:`._capture_main` emits and
    what a fixture observation supplies.
    """
    jsonish: list[dict] = []
    for entry in responses:
        body = entry.get("body")
        if body is None:
            continue
        arrays = find_record_arrays(body)
        arrays.sort(key=lambda a: (a["job_score"], a["count"]), reverse=True)
        if not arrays:
            continue
        jsonish.append({
            "method": entry.get("method", "GET"),
            "url": entry.get("url", ""),
            "status": entry.get("status"),
            "content_type": entry.get("content_type"),
            "record_arrays": arrays[:5],
            "counts": find_counts(body),
            "top_level_keys": (
                sorted(body.keys())[:25] if isinstance(body, dict)
                else f"<list len={len(body)}>"
            ),
        })
    jsonish.sort(
        key=lambda r: max((a["job_score"] for a in r["record_arrays"]), default=0),
        reverse=True,
    )

    all_xhr: list[dict[str, Any]] = [
        {
            "method": r.get("method"),
            "url": (r.get("url") or "")[:300],
            "status": r.get("status"),
            "type": r.get("content_type"),
        }
        for r in responses
        if r.get("resource_type") in ("xhr", "fetch")
    ][:60]
    dom_repetition = sketch_dom_repetition(html)

    report: dict[str, Any] = {
        "entry_url": entry_url,
        "page_title": page_title,
        "nav_error": nav_error,
        "wall_seconds": round(wall_seconds, 1),
        "dollars": 0.0,
        "responses_total": len(responses),
        "job_like_json_responses": jsonish[:8],
        "embedded_json": scan_embedded_json(html),
        "dom_repetition": dom_repetition,
        "all_xhr": all_xhr,
    }
    # Last-resort size cap: trim the raw XHR list, then the DOM sketch. Slice the
    # typed locals so the result stays a list (indexing report[...] is a union).
    if len(json.dumps(report)) > _MAX_REPORT_BYTES:
        report["all_xhr"] = all_xhr[:15]
    if len(json.dumps(report)) > _MAX_REPORT_BYTES:
        report["dom_repetition"] = dom_repetition[:5]
    return report


# --------------------------------------------------------------------------
# live capture (out of process — playwright never enters THIS process)
# --------------------------------------------------------------------------

CaptureFn = Callable[[str], Awaitable[dict[str, Any]]]


async def _subprocess_capture(url: str) -> dict[str, Any]:
    """Run the Playwright capture in a child process and parse its report JSON.

    ``playwright`` is imported only by the child (:mod:`._capture_main`), so it
    never lands in this process's ``sys.modules`` — the replay path's runtime
    guard stays satisfied even when the same worker later runs a nightly harvest.
    """
    backend_root = Path(__file__).resolve().parents[3]  # src/backend
    repo_root = backend_root.parents[1]                 # src/backend → src → repo root
    # The child imports the discovery package, which transitively imports
    # ``scripts.shared`` (at the repo root) and ``api.*`` (under src/backend), so
    # both must be on PYTHONPATH regardless of the worker's own cwd/env.
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(backend_root), str(repo_root), prior) if p
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "api.services.discovery._capture_main", "--url", url,
        cwd=str(backend_root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise ObserveError(f"discovery observer subprocess timed out after {_SUBPROCESS_TIMEOUT_S}s")
    if proc.returncode != 0:
        raise ObserveError(
            f"discovery observer subprocess failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace')[:500]}"
        )
    try:
        report: dict[str, Any] = json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ObserveError(f"discovery observer produced non-JSON output: {exc}") from exc
    return report


class ObserveError(RuntimeError):
    """The observation step failed (browser crash, timeout, non-JSON)."""


async def observe(url: str, *, capture_fn: CaptureFn | None = None) -> dict[str, Any]:
    """Observe ``url`` and return the compact evidence report.

    ``capture_fn`` is injectable so tests supply a fixture observation instead of
    launching Chromium. In production it defaults to the out-of-process
    subprocess capture.
    """
    runner = capture_fn or _subprocess_capture
    return await runner(url)
