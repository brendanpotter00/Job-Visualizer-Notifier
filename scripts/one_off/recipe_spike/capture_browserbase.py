"""DISCOVERY SIDE, CLOUD ARM — capture.py rerun through a Browserbase browser.

Same evidence, different vantage point: the page loads in a Browserbase-hosted
Chromium (driven via the Stagehand SDK + Playwright-over-CDP) instead of local
headless Chromium. The point of this arm is to measure whether a CLOUD /
datacenter IP gets bot-walled where a LOCAL residential IP does not — and
vice-versa. Diff report_browserbase.json against report.json for the same
target: the two share the same structure and keys.

This file is NEVER imported by replay.py (replay's import guard explicitly
forbids stagehand/browserbase on the deterministic path).

Credentials: BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID, read from the
environment or from the repo root .env.local. Without them the script prints
a notice and exits 0, so batch runs can include this arm unconditionally.
See BROWSERBASE_SETUP.md. The key value is never printed or logged.

Free tier guard: the free plan allots 1 browser-hour and 3 agent calls per
month. This script makes ZERO act/extract/agent calls (agent quota untouched)
and asks Browserbase to hard-kill the session server-side after
SESSION_TIMEOUT_SECONDS even if we crash, so a run can never leak more than a
few minutes of the monthly hour. Actual consumption lands in the report as
browser_seconds + free_tier_note.

Usage:
    python capture_browserbase.py --target amazon --url "https://www.amazon.jobs/en/search?..."
    python capture_browserbase.py --target meta --url "https://www.metacareers.com/jobsearch" --scroll 3

Outputs (under captures/<target>/):
    report_browserbase.json     same structure as report.json — diff the two
    browserbase/raw/NNN.json    full bodies of the JSON responses worth inspecting
    browserbase/page.html       final rendered HTML as the cloud browser saw it
    browserbase/embedded_*.json JSON islands found in that HTML
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

# Reuse capture.py's analysis helpers — one scoring/report vocabulary for both
# arms, so the local and cloud reports stay directly diffable.
from capture import (
    CAPTURES,
    MAX_RAW_BODY_BYTES,
    find_counts,
    find_record_arrays,
    scan_embedded_json,
    score_object,  # noqa: F401 — re-exported for parity; used via find_record_arrays
    sketch_dom_repetition,
)

HERE = Path(__file__).parent

REQUIRED_ENV = ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID")

# Server-side session lifetime cap (seconds). A capture is typically <90s;
# if this process dies mid-run, Browserbase still reaps the session at this
# mark, so one crashed run can cost at most ~5 of the 60 free monthly minutes.
SESSION_TIMEOUT_SECONDS = 300

# sessions.start() requires a model name in its signature. This script never
# issues an act/extract/observe/agent call, so no model/LLM is invoked, no
# MODEL_API_KEY is needed for the capture itself, and no free-tier agent
# calls are consumed.
MODEL_NAME = "anthropic/claude-sonnet-4-5"

FREE_TIER_NOTE_TEMPLATE = (
    "Browserbase free tier = 1 browser-hour + 3 agent calls per month. "
    "This run held a cloud browser for ~{seconds}s (~{pct:.2f}% of the monthly hour). "
    "Zero act/extract/agent calls were made, so the agent-call quota is untouched. "
    "The session carries a {cap}s server-side timeout as a crash guard."
)


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------

def _find_env_local() -> Path | None:
    """Walk up from this file looking for a .env.local (repo root has one).

    Works both from the main checkout and from a git worktree nested under
    .claude/worktrees/ (the walk keeps going past the worktree root).
    """
    for parent in (HERE, *HERE.parents):
        candidate = parent / ".env.local"
        if candidate.is_file():
            return candidate
    return None


def load_env_local() -> None:
    """Load KEY=VALUE lines from .env.local without overriding the real env.

    Values are only placed into os.environ — never printed.
    """
    env_file = _find_env_local()
    if env_file is None:
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def require_credentials() -> None:
    missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
    if missing:
        print("no Browserbase credentials — skipping cloud arm")
        print(
            f"  set {' and '.join(missing)} in the environment or the repo root "
            ".env.local to enable it (see BROWSERBASE_SETUP.md)"
        )
        raise SystemExit(0)


# --------------------------------------------------------------------------
# capture over CDP
# --------------------------------------------------------------------------

async def capture_over_cdp(
    cdp_url: str, target: str, url: str, scrolls: int, wait: str, settle_ms: int
) -> dict:
    """Mirror of capture.py's capture(), but attached to a remote browser.

    Writes raw artifacts under captures/<target>/browserbase/ so the local
    arm's raw/, page.html and embedded_*.json files are never clobbered.
    """
    out_dir = CAPTURES / target
    bb_dir = out_dir / "browserbase"
    raw_dir = bb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for stale in raw_dir.glob("*.json"):
        stale.unlink()
    for stale in bb_dir.glob("embedded_*.json"):
        stale.unlink()

    responses: list[dict] = []
    pending: list[asyncio.Task] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        # Browserbase sessions ship with a default context/page carrying the
        # platform's own fingerprint — deliberately NOT overridden here, since
        # that fingerprint (plus the cloud IP) is exactly what this arm measures.
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        async def record(response) -> None:
            try:
                request = response.request
                content_type = (response.headers or {}).get("content-type", "")
                entry = {
                    "method": request.method,
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type.split(";")[0],
                    "resource_type": request.resource_type,
                }
                if request.method == "POST":
                    body = request.post_data
                    if body:
                        entry["request_body"] = body[:2000]
                is_jsonish = "json" in content_type or response.url.endswith(".json")
                if is_jsonish and response.status < 400:
                    body_bytes = await response.body()
                    entry["bytes"] = len(body_bytes)
                    if len(body_bytes) <= MAX_RAW_BODY_BYTES:
                        try:
                            payload = json.loads(body_bytes.decode("utf-8", "replace"), strict=False)
                        except Exception as exc:  # noqa: BLE001 - evidence, not control flow
                            entry["parse_error"] = str(exc)[:200]
                        else:
                            arrays = find_record_arrays(payload)
                            arrays.sort(key=lambda a: (a["job_score"], a["count"]), reverse=True)
                            entry["record_arrays"] = arrays[:5]
                            entry["counts"] = find_counts(payload)
                            entry["top_level_keys"] = (
                                sorted(payload.keys())[:25] if isinstance(payload, dict) else f"<list len={len(payload)}>"
                            )
                            if arrays:
                                index = len(list(raw_dir.glob("*.json")))
                                raw_path = raw_dir / f"{index:03d}.json"
                                raw_path.write_text(json.dumps(payload, indent=1)[:4_000_000])
                                entry["raw_file"] = str(raw_path.relative_to(out_dir))
                responses.append(entry)
            except Exception as exc:  # noqa: BLE001
                responses.append({"url": getattr(response, "url", "?"), "capture_error": str(exc)[:200]})

        page.on("response", lambda r: pending.append(asyncio.create_task(record(r))))

        nav_error = None
        try:
            await page.goto(url, wait_until=wait, timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            nav_error = str(exc)[:300]

        for _ in range(scrolls):
            try:
                await page.mouse.wheel(0, 4000)
                await page.wait_for_timeout(1200)
            except Exception:  # noqa: BLE001
                break

        await page.wait_for_timeout(settle_ms)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        html = await page.content()
        (bb_dir / "page.html").write_text(html[:3_000_000])
        title = await page.title()
        await browser.close()

    embedded = scan_embedded_json(html, bb_dir)
    dom = sketch_dom_repetition(html)

    jsonish = [r for r in responses if r.get("record_arrays")]
    jsonish.sort(key=lambda r: max((a["job_score"] for a in r["record_arrays"]), default=0), reverse=True)

    return {
        "page_title": title,
        "nav_error": nav_error,
        "responses_total": len(responses),
        "job_like_json_responses": jsonish[:8],
        "embedded_json": embedded,
        "dom_repetition": dom,
        "all_xhr": [
            {"method": r.get("method"), "url": r.get("url", "")[:300], "status": r.get("status"), "type": r.get("content_type")}
            for r in responses
            if r.get("resource_type") in ("xhr", "fetch")
        ][:60],
    }


# --------------------------------------------------------------------------
# session lifecycle
# --------------------------------------------------------------------------

def start_session():
    """Create the Browserbase session via Stagehand. Returns (client, session_id, cdp_url)."""
    from stagehand import Stagehand  # imported lazily: the no-credential path must not need it

    client = Stagehand(
        browserbase_api_key=os.environ["BROWSERBASE_API_KEY"],
        browserbase_project_id=os.environ["BROWSERBASE_PROJECT_ID"],
        # Optional; only forwarded if present. Not required for plain navigation.
        model_api_key=os.environ.get("MODEL_API_KEY"),
    )
    try:
        response = client.sessions.start(
            model_name=MODEL_NAME,
            browserbase_session_create_params={
                "project_id": os.environ["BROWSERBASE_PROJECT_ID"],
                "timeout": SESSION_TIMEOUT_SECONDS,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "could not start a Browserbase session: "
            f"{type(exc).__name__}: {exc}\n"
            "  (check that BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID are valid; "
            "if the API demands a model key, additionally set MODEL_API_KEY)"
        ) from exc

    session_id = response.data.session_id
    cdp_url = response.data.cdp_url
    return client, session_id, cdp_url


def end_session(client, session_id: str) -> None:
    """Release the session so browser-minutes stop accruing. Never raises."""
    try:
        client.sessions.end(session_id)
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: failed to end session {session_id} cleanly ({type(exc).__name__}); "
            f"Browserbase will reap it at the {SESSION_TIMEOUT_SECONDS}s session timeout",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture discovery evidence for one careers site through a Browserbase cloud browser"
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--scroll", type=int, default=2, help="scroll bursts after load")
    parser.add_argument("--wait", default="networkidle", choices=["load", "domcontentloaded", "networkidle", "commit"])
    parser.add_argument("--settle-ms", type=int, default=3000)
    args = parser.parse_args()

    load_env_local()
    require_credentials()

    wall_started = time.time()
    client, session_id, cdp_url = start_session()
    session_started = time.time()
    try:
        if not cdp_url:
            raise SystemExit(
                f"session {session_id} started but returned no CDP URL — cannot attach Playwright"
            )
        captured = asyncio.run(
            capture_over_cdp(cdp_url, args.target, args.url, args.scroll, args.wait, args.settle_ms)
        )
    finally:
        end_session(client, session_id)
    browser_seconds = round(time.time() - session_started, 1)

    report = {
        # same keys as capture.py's report.json, in the same order …
        "target": args.target,
        "entry_url": args.url,
        "page_title": captured["page_title"],
        "nav_error": captured["nav_error"],
        "wall_seconds": round(time.time() - wall_started, 1),
        "browser_seconds": browser_seconds,
        "dollars": 0.0,  # free tier: the monthly browser-hour is included, hard-capped, never billed
        "responses_total": captured["responses_total"],
        "job_like_json_responses": captured["job_like_json_responses"],
        "embedded_json": captured["embedded_json"],
        "dom_repetition": captured["dom_repetition"],
        "all_xhr": captured["all_xhr"],
        # … plus cloud-arm extras (append-only, so shared keys diff cleanly)
        "arm": "browserbase",
        "session_id": session_id,
        "free_tier_note": FREE_TIER_NOTE_TEMPLATE.format(
            seconds=browser_seconds,
            pct=browser_seconds / 36.0,
            cap=SESSION_TIMEOUT_SECONDS,
        ),
    }

    out_dir = CAPTURES / args.target
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report_browserbase.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(json.dumps({
        "target": report["target"],
        "page_title": report["page_title"],
        "nav_error": report["nav_error"],
        "wall_seconds": report["wall_seconds"],
        "browser_seconds": report["browser_seconds"],
        "responses_total": report["responses_total"],
        "job_like_json_responses": len(report["job_like_json_responses"]),
        "embedded_json": len(report["embedded_json"]),
        "report": str(report_path),
    }, indent=2))


if __name__ == "__main__":
    main()
