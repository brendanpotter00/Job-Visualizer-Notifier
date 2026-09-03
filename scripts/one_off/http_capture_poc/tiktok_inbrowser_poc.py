"""Prove the 'requires-browser recipe' tier: run TikTok's SAME deterministic API call
INSIDE a headless browser (page.evaluate on the site's origin) — the pattern JVN's
existing tiktok_jobs_scraper uses. If this returns jobs, TikTok is a deterministic
in-browser-fetch recipe (no LLM), not an agent/DOM board."""
import asyncio
import json
import os
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[3]
for line in (ROOT / ".env.local").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
KEY, PROJ = os.environ["BROWSERBASE_API_KEY"], os.environ["BROWSERBASE_PROJECT_ID"]

ORIGIN = "https://lifeattiktok.com/"
API = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
BODY = {"limit": 10, "offset": 0, "keyword": "software engineer",
        "recruitment_id_list": [], "job_category_id_list": [],
        "subject_id_list": [], "location_code_list": []}

JS = """
async ({url, headers, body}) => {
  const r = await fetch(url, {method:'POST', headers, body: JSON.stringify(body), credentials:'same-origin'});
  const text = await r.text();
  return {status: r.status, text};
}
"""


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        s = (await c.post("https://api.browserbase.com/v1/sessions",
                          headers={"X-BB-API-Key": KEY, "Content-Type": "application/json"},
                          json={"projectId": PROJ, "timeout": 180})).json()
    print("session:", s["id"])
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(s["connectUrl"])
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)  # settle on-origin
            res = await page.evaluate(JS, {
                "url": API,
                "headers": {"content-type": "application/json", "website-path": "tiktok"},
                "body": BODY,
            })
        finally:
            await browser.close()

    print("in-browser fetch status:", res["status"])
    try:
        data = json.loads(res["text"])
    except Exception:
        print("non-JSON:", res["text"][:200]); return
    # count jobs in the response
    def biggest(o, d=0):
        best = 0
        if d > 6: return 0
        if isinstance(o, list) and o and isinstance(o[0], dict):
            if any(any(h in str(k).lower() for h in ("title", "job", "id")) for k in o[0]): best = len(o)
            for x in o: best = max(best, biggest(x, d+1))
        elif isinstance(o, dict):
            for v in o.values(): best = max(best, biggest(v, d+1))
        return best
    n = biggest(data)
    code = data.get("code") if isinstance(data, dict) else None
    print(f"payload code={code}, jobs found={n}")
    if res["status"] == 200 and n > 0:
        print(f"\n✅ IN-BROWSER RECIPE WORKS — TikTok returns {n} jobs via a deterministic in-browser POST.")
        print("   => 'requires-browser' = a Tier-1b in-browser-fetch recipe (no LLM, no DOM parsing), not an agent board.")
    else:
        print("\n⚠️ in-browser fetch did not return jobs — see status/code above.")


asyncio.run(main())
