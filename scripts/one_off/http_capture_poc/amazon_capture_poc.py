"""Tier-1 validation POC — capture Amazon's jobs API via a Browserbase session, then
replay it with plain httpx (no browser, no LLM). Proves: discover-the-API-once ->
cheap-deterministic-replay. Prints a structured report to stdout. See RESULTS.md.

Run from the worktree root:  .venv/bin/python scripts/one_off/http_capture_poc/amazon_capture_poc.py
Needs BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID in .env.local (paid plan).
"""
import asyncio
import json
import os
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

# worktree root = scripts/one_off/http_capture_poc/ -> up 3
ROOT = Path(__file__).resolve().parents[3]
for line in (ROOT / ".env.local").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

BB_KEY = os.environ["BROWSERBASE_API_KEY"]
BB_PROJECT = os.environ["BROWSERBASE_PROJECT_ID"]

# A page that lists Amazon jobs (fires the search XHR on load).
TARGET = "https://www.amazon.jobs/en/search?base_query=software&loc_query="
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


def _looks_job_json(body: str):
    """Return (is_jobish, parsed, job_count) for a response body."""
    try:
        data = json.loads(body)
    except Exception:
        return (False, None, 0)
    if isinstance(data, dict):
        for key in ("jobs", "hits", "results", "data", "items"):
            v = data.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                keys = set(v[0].keys())
                if keys & {"title", "job_title", "jobTitle", "name", "id", "id_icims"}:
                    return (True, data, len(v))
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if set(data[0].keys()) & {"title", "job_title", "name", "id"}:
            return (True, data, len(data))
    return (False, data, 0)


async def main() -> None:
    print("=== 1. create Browserbase session ===")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.browserbase.com/v1/sessions",
            headers={"X-BB-API-Key": BB_KEY, "Content-Type": "application/json"},
            json={"projectId": BB_PROJECT, "timeout": 300},
        )
        r.raise_for_status()
        session = r.json()
    connect_url = session["connectUrl"]
    print("session id:", session.get("id"))

    captured: list[dict] = []
    print("\n=== 2. drive with Playwright over CDP, capture JSON XHR/fetch ===")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(response):
            try:
                req = response.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                ct = (response.headers or {}).get("content-type", "")
                if "json" not in ct.lower():
                    return
                body = await response.text()
                is_job, _, count = _looks_job_json(body)
                captured.append({
                    "url": req.url, "method": req.method, "status": response.status,
                    "is_job": is_job, "count": count,
                    "req_headers": dict(req.headers), "body_len": len(body),
                    "body_snippet": body[:300],
                })
            except Exception as exc:  # noqa: BLE001
                captured.append({"error": f"{type(exc).__name__}: {exc}"})

        page.on("response", on_response)
        try:
            await page.goto(TARGET, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(6000)  # let the search XHR fire
        finally:
            await browser.close()

    print(f"captured {len(captured)} JSON xhr/fetch responses")
    for c in captured:
        if "error" in c:
            print("  ! capture error:", c["error"]); continue
        flag = "JOBS" if c["is_job"] else "    "
        print(f"  [{flag}] {c['method']} {c['status']} count={c['count']:>4} len={c['body_len']:>7}  {c['url'][:110]}")

    job_candidates = [c for c in captured if c.get("is_job")]
    if not job_candidates:
        print("\nNO job-shaped JSON request captured — target may have changed / bot-walled.")
        return
    best = max(job_candidates, key=lambda c: c["count"])
    print(f"\n=== 3. discovered jobs API ===\n  {best['method']} {best['url']}\n  browser saw {best['count']} jobs")

    print("\n=== 4. REPLAY with plain httpx (no browser, no LLM) ===")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        rr = await client.get(best["url"], headers={"User-Agent": UA, "Accept": "application/json"})
    print(f"  replay status: {rr.status_code}  bytes: {len(rr.text)}")
    is_job2, _, count2 = _looks_job_json(rr.text)
    if is_job2 and count2 > 0:
        print(f"  ✅ REPLAY SUCCESS — plain httpx returned {count2} jobs (browser saw {best['count']})")
        print("  => Tier-1 http_json is VALID for this board: capture once, replay cheaply.")
    else:
        print(f"  ❌ replay did not return jobs (is_job={is_job2}, count={count2}); snippet: {rr.text[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
