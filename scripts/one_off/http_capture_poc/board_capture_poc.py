"""Generalized Tier-1 capture POC — point at ANY job board. Captures every JSON XHR/fetch
(method, url, headers, POST body), finds the job-shaped response, then does a TWO-TIER
replay to classify the board:
  DETERMINISTIC       — replays with just a User-Agent (fully public)
  NEEDS-STABLE-HEADERS— replays only with the captured custom headers (e.g. TikTok's
                        website-path) but no cookies → deterministic IF those are static
  REQUIRES-BROWSER    — replays only with session cookies / rotating tokens, or no API → fallback
Also probes the Browserbase session recording endpoint.

Usage:  .venv/bin/python board_capture_poc.py <label> <url>
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[3]
for line in (ROOT / ".env.local").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

BB_KEY = os.environ["BROWSERBASE_API_KEY"]
BB_PROJECT = os.environ["BROWSERBASE_PROJECT_ID"]
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

LABEL = sys.argv[1] if len(sys.argv) > 1 else "board"
URL = sys.argv[2] if len(sys.argv) > 2 else "https://www.amazon.jobs/en/search?base_query=software"

_JOB_KEY_HINTS = ("title", "job", "position", "role", "req", "posting")


def _biggest_job_array(obj, depth=0):
    """Recursively find the largest list-of-dicts whose dicts look job-ish. Returns (count, sample_keys)."""
    best = (0, None)
    if depth > 6:
        return best
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj[:5]):
            keys = set()
            for x in obj[:5]:
                keys |= {str(k).lower() for k in x.keys()}
            if any(any(h in k for h in _JOB_KEY_HINTS) for k in keys):
                best = (len(obj), sorted(keys)[:12])
        for x in obj:
            best = max(best, _biggest_job_array(x, depth + 1), key=lambda t: t[0])
    elif isinstance(obj, dict):
        for v in obj.values():
            best = max(best, _biggest_job_array(v, depth + 1), key=lambda t: t[0])
    return best


def _job_count(body: str):
    try:
        data = json.loads(body)
    except Exception:
        return (0, None)
    count, keys = _biggest_job_array(data)
    return (count, keys)


async def _replay(method, url, headers, post_data):
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        if method == "POST":
            r = await c.post(url, headers=headers, content=(post_data or ""))
        else:
            r = await c.get(url, headers=headers)
    count, _ = _job_count(r.text)
    return r.status_code, len(r.text), count


async def main() -> None:
    print(f"=== {LABEL}: {URL} ===")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://api.browserbase.com/v1/sessions",
                              headers={"X-BB-API-Key": BB_KEY, "Content-Type": "application/json"},
                              json={"projectId": BB_PROJECT, "timeout": 300})
        r.raise_for_status()
        session = r.json()
    sid, connect_url = session["id"], session["connectUrl"]
    print("session id:", sid)

    captured = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(connect_url)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def on_response(resp):
            try:
                req = resp.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                if "json" not in (resp.headers or {}).get("content-type", "").lower():
                    return
                body = await resp.text()
                count, keys = _job_count(body)
                captured.append({"url": req.url, "method": req.method, "status": resp.status,
                                 "count": count, "keys": keys, "headers": dict(req.headers),
                                 "post_data": req.post_data, "body_len": len(body)})
            except Exception:
                pass
        page.on("response", on_response)
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(7000)
        finally:
            await browser.close()

    print(f"captured {len(captured)} JSON xhr/fetch:")
    for c in sorted(captured, key=lambda x: -x["count"]):
        flag = "JOBS" if c["count"] else "    "
        print(f"  [{flag}] {c['method']} {c['status']} count={c['count']:>4} len={c['body_len']:>7} {c['url'][:95]}")

    cands = [c for c in captured if c["count"] > 0]
    if not cands:
        print(f"\nRESULT [{LABEL}]: REQUIRES-BROWSER (no job-shaped JSON API captured — likely SSR or bot-walled)")
    else:
        best = max(cands, key=lambda c: c["count"])
        print(f"\nDISCOVERED: {best['method']} {best['url'][:120]}")
        print(f"  browser saw {best['count']} jobs; sample keys: {best['keys']}")
        # Tier A: minimal headers
        minimal = {"User-Agent": UA, "Accept": "application/json"}
        if best["method"] == "POST":
            minimal["Content-Type"] = best["headers"].get("content-type", "application/json")
        sa, la, ca = await _replay(best["method"], best["url"], minimal, best["post_data"])
        print(f"  replay A (minimal UA)      -> {sa}, {la}b, {ca} jobs")
        # Tier B: full captured headers minus cookie/host/content-length
        full = {k: v for k, v in best["headers"].items()
                if k.lower() not in ("cookie", "host", "content-length", ":authority", ":method", ":path", ":scheme")}
        full["User-Agent"] = UA
        sb, lb, cb = await _replay(best["method"], best["url"], full, best["post_data"])
        print(f"  replay B (full, no cookie) -> {sb}, {lb}b, {cb} jobs")
        if ca > 0:
            print(f"\nRESULT [{LABEL}]: ✅ DETERMINISTIC (public — replays with just a User-Agent). Tier-1 works.")
        elif cb > 0:
            print(f"\nRESULT [{LABEL}]: 🟡 NEEDS-STABLE-HEADERS (replays with captured headers, no cookies) — Tier-1 works IF those headers are static (e.g. a website-path header).")
        else:
            print(f"\nRESULT [{LABEL}]: 🔴 REQUIRES-BROWSER (only replays inside the browser session — cookies/rotating tokens). Falls back to Tier 2/3.")

    # Recording question
    print("\n=== recording probe ===")
    async with httpx.AsyncClient(timeout=30) as client:
        rec = await client.get(f"https://api.browserbase.com/v1/sessions/{sid}/recording",
                               headers={"X-BB-API-Key": BB_KEY})
    print(f"  GET /v1/sessions/{{id}}/recording -> {rec.status_code}, {len(rec.text)} bytes"
          + (f" (recording present: {rec.text[:60]}...)" if rec.status_code == 200 and len(rec.text) > 5 else ""))


if __name__ == "__main__":
    asyncio.run(main())
