"""Throwaway discovery probe: record the exact request (headers+body) the site
sends to the job search API. Not part of the harness."""
import asyncio
import json

from playwright.async_api import async_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def main():
    hits = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = await ctx.new_page()

        async def on_request(req):
            if "search/job/posts" in req.url:
                hits.append(
                    {
                        "url": req.url,
                        "method": req.method,
                        "headers": await req.all_headers(),
                        "post_data": req.post_data,
                    }
                )

        page.on("request", lambda r: asyncio.create_task(on_request(r)))
        await page.goto("https://lifeattiktok.com/search", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        await ctx.close()
        await browser.close()
    print(json.dumps(hits, indent=2))


asyncio.run(main())
