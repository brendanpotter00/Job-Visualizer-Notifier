"""One-off: dump rendered rows on the typed pages and reconcile with main.json ids."""
import asyncio
import json
import re

from playwright.async_api import async_playwright

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

URLS = {
    "experienced": "https://www.janestreet.com/join-jane-street/open-roles/?type=experienced-candidates",
    "students": "https://www.janestreet.com/join-jane-street/open-roles/?type=students-and-new-grads",
}

data = json.load(open("scripts/one_off/recipe_spike/captures/janestreet/raw/000.json"))
ids_all = {str(d["id"]) for d in data}
ids_exp = {str(d["id"]) for d in data if d["availability"] == "Full-Time: Experienced"}
ids_stu = ids_all - ids_exp


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=UA)
        page = await ctx.new_page()
        seen = {}
        for label, url in URLS.items():
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            await page.wait_for_timeout(2500)
            hrefs = await page.eval_on_selector_all(
                "a[href*='/position/']", "els => els.map(e => e.getAttribute('href'))"
            )
            ids = set()
            for h in hrefs:
                m = re.search(r"/position/(\d+)", h or "")
                if m:
                    ids.add(m.group(1))
            seen[label] = ids
            rows = await page.eval_on_selector_all(
                ".job", "els => els.slice(0, 6).map(e => e.textContent.trim().slice(0, 120))"
            )
            print(f"{label}: {len(hrefs)} links, {len(ids)} distinct ids; sample rows:")
            for r in rows:
                print("   |", r)
        await ctx.close()
        await browser.close()

    rendered = seen["experienced"] | seen["students"]
    print("\nrendered distinct ids:", len(rendered))
    print("main.json ids:", len(ids_all))
    print("rendered - main.json:", sorted(rendered - ids_all)[:10])
    missing = ids_all - rendered
    print("main.json - rendered:", len(missing))
    by_id = {str(d["id"]): d for d in data}
    for i in sorted(missing)[:30]:
        d = by_id[i]
        print("   missing:", i, d["position"][:40], d["city"], d["availability"])


asyncio.run(main())
