"""One-off discovery: capture full request+response for metacareers.com /graphql POSTs.

Writes captures/meta/graphql/NNN_req.txt (headers + post body) and NNN_resp.txt
(full response body) for every POST to /graphql seen while loading the jobs page.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).parent
OUT = HERE / "graphql"
OUT.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.metacareers.com/jobs"


async def main() -> None:
    for stale in OUT.glob("*"):
        stale.unlink()

    seen = []
    pending: list[asyncio.Task] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        async def record(response) -> None:
            req = response.request
            if req.method != "POST" or "/graphql" not in response.url:
                return
            index = len(seen)
            seen.append(response.url)
            headers = await req.all_headers()
            body = req.post_data or ""
            (OUT / f"{index:03d}_req.txt").write_text(
                json.dumps({"url": response.url, "headers": headers}, indent=1)
                + "\n\nPOST_BODY:\n" + body
            )
            try:
                text = await response.text()
            except Exception as exc:  # noqa: BLE001
                text = f"<<body read failed: {exc}>>"
            (OUT / f"{index:03d}_resp.txt").write_text(text)

        page.on("response", lambda r: pending.append(asyncio.create_task(record(r))))

        await page.goto(URL, wait_until="networkidle", timeout=60_000)
        for _ in range(3):
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(1200)
        await page.wait_for_timeout(3000)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # Also grab cookies the page ended up with, for the forgeability analysis.
        cookies = await context.cookies()
        (OUT / "cookies.json").write_text(json.dumps(cookies, indent=1))

        await context.close()
        await browser.close()

    print(f"captured {len(seen)} graphql POSTs -> {OUT}")
    for i, u in enumerate(seen):
        print(f"  {i:03d} {u}")


if __name__ == "__main__":
    asyncio.run(main())
