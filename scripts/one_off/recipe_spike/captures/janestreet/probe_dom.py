"""One-off: count job rows the site itself renders on both typed listing pages."""
import asyncio

from playwright.async_api import async_playwright

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

URLS = [
    "https://www.janestreet.com/join-jane-street/open-roles/?type=experienced-candidates",
    "https://www.janestreet.com/join-jane-street/open-roles/?type=students-and-new-grads",
]


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=UA)
        page = await ctx.new_page()
        for url in URLS:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            await page.wait_for_timeout(2500)
            for sel in ["a[href*='/position/']", ".job", ".position", "[class*='job-listing']"]:
                n = await page.locator(sel).count()
                print(f"{url}\n  {sel!r}: {n}")
            # any visible total text
            body = await page.inner_text("body")
            for line in body.splitlines():
                low = line.strip().lower()
                if ("role" in low or "position" in low) and any(ch.isdigit() for ch in low):
                    print("  count-ish line:", line.strip()[:100])
        await ctx.close()
        await browser.close()


asyncio.run(main())
