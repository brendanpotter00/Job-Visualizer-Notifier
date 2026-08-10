"""ONE bounded Browserbase Stagehand validation run (E7 pivot de-risker).

Proves whether a cloud browser-agent can (a) read jobs off a REAL rendered page
and (b) yield a REUSABLE artifact (observe() actions with selectors + a
schema'd extract), bounded to 2-3 pages. NOT production code. Throwaway.

Targets:
  1. YC raindrop per-company jobs page — the case the Sonnet-authors-JSON path
     was reported to fail on. JS-rendered; single page.
  2. amazon.jobs search — walk exactly 2 pages to prove the bound + that
     observe() returns a replayable "next page" action.

Credentials are read from the worktree-root .env.local; nothing is printed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values
from stagehand import Stagehand

WORKTREE_ROOT = Path("/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/worktrees/2")
ENV = dotenv_values(WORKTREE_ROOT / ".env.local")

BB_KEY = ENV.get("BROWSERBASE_API_KEY") or os.environ.get("BROWSERBASE_API_KEY")
BB_PROJECT = ENV.get("BROWSERBASE_PROJECT_ID") or os.environ.get("BROWSERBASE_PROJECT_ID")
ANTHROPIC_KEY = ENV.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

MODEL = os.environ.get("SPIKE_MODEL", "anthropic/claude-sonnet-4-5")

JOB_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["title"],
            },
        }
    },
    "required": ["jobs"],
}

report: dict = {"model": MODEL, "phases": []}


def summarize(obj):
    """Best-effort structural summary of a Stagehand response object."""
    for attr in ("data", "model_dump", "__dict__"):
        if attr == "model_dump" and hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                pass
        if hasattr(obj, attr) and attr != "model_dump":
            return getattr(obj, attr)
    return repr(obj)[:2000]


def extract_jobs(client, sid, instruction):
    resp = client.sessions.extract(sid, instruction=instruction, schema=JOB_SCHEMA)
    data = summarize(resp)
    return data


def main() -> None:
    if not (BB_KEY and ANTHROPIC_KEY):
        print("MISSING CREDS", file=sys.stderr)
        sys.exit(2)

    t0 = time.time()
    with Stagehand(
        server="remote",
        browserbase_api_key=BB_KEY,
        browserbase_project_id=BB_PROJECT,
        model_api_key=ANTHROPIC_KEY,
    ) as client:
        started = client.sessions.start(
            model_name=MODEL,
            browser={"type": "browserbase"},
            dom_settle_timeout_ms=15000,
            self_heal=True,
            system_prompt=(
                "You read public job-board pages. Never crawl a whole board; "
                "work only on the page you are on."
            ),
        )
        sid = getattr(started, "id", None) or summarize(started).get("id")
        report["session_id"] = sid
        report["session_start"] = summarize(started)

        # ---- PHASE 1: YC raindrop (the old-path failure case) ----
        p1: dict = {"name": "yc_raindrop", "url": "https://www.ycombinator.com/companies/raindrop/jobs"}
        try:
            client.sessions.navigate(sid, url=p1["url"])
            time.sleep(2)
            obs = client.sessions.observe(sid, instruction="find the job posting rows and any pagination or 'load more' control")
            p1["observe"] = summarize(obs)
            p1["extract"] = extract_jobs(client, sid, "extract every job posting on this page with its title, location, and apply/link url")
        except Exception as exc:  # noqa: BLE001
            p1["error"] = f"{type(exc).__name__}: {exc}"
        report["phases"].append(p1)

        # ---- PHASE 2: amazon.jobs, bounded 2-page walk ----
        p2: dict = {"name": "amazon_2page", "url": "https://www.amazon.jobs/en/search?base_query=software+engineer"}
        try:
            client.sessions.navigate(sid, url=p2["url"])
            time.sleep(2)
            obs_next = client.sessions.observe(sid, instruction="find the 'next page' pagination control")
            p2["observe_next_page_action"] = summarize(obs_next)
            p2["extract_page1"] = extract_jobs(client, sid, "extract the job results listed on this page: title, location, url")
            # act to page 2 using the observed affordance (proves reusable action)
            act = client.sessions.act(sid, input="click the next page button to go to page 2 of results")
            p2["act_to_page2"] = summarize(act)
            time.sleep(2)
            p2["extract_page2"] = extract_jobs(client, sid, "extract the job results listed on this page: title, location, url")
        except Exception as exc:  # noqa: BLE001
            p2["error"] = f"{type(exc).__name__}: {exc}"
        report["phases"].append(p2)

        report["wall_seconds"] = round(time.time() - t0, 1)
        try:
            client.sessions.end(sid)
        except Exception:
            pass

    out = WORKTREE_ROOT / "scripts/one_off/stagehand_spike/spike_result.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print("WROTE", out)
    # compact console summary
    for ph in report["phases"]:
        print("PHASE", ph["name"], "error=", ph.get("error"))


if __name__ == "__main__":
    main()
