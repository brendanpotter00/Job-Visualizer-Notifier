"""Playwright capture SUBPROCESS entrypoint (E7 Phase 3b).

Run ONLY as ``python -m api.services.discovery._capture_main --url <url>`` — never
imported. This is the one module that imports ``playwright``; because the observer
invokes it as a *child process* (see ``observer._subprocess_capture``), ``playwright``
never enters the parent worker's ``sys.modules``, so the replay path's runtime
guard (``recipe_runner.assert_no_agent_imports``) stays satisfied.

It navigates the URL in a local headless Chromium, records every JSON network
response + the rendered DOM, then prints the compact evidence report (built by the
pure ``observer.build_report``) as JSON on stdout. All diagnostics go to stderr so
stdout stays parseable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any, cast

from playwright.async_api import async_playwright  # the ONLY playwright import site

from api.services.discovery import observer

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_RAW_BODY_BYTES = 6_000_000


async def _capture(url: str, scrolls: int, wait: str, settle_ms: int) -> dict[str, Any]:
    responses: list[dict] = []
    pending: list[asyncio.Task] = []
    started = time.time()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        async def record(response: Any) -> None:  # playwright Response
            try:
                request = response.request
                content_type = (response.headers or {}).get("content-type", "")
                entry: dict[str, Any] = {
                    "method": request.method,
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type.split(";")[0],
                    "resource_type": request.resource_type,
                }
                is_jsonish = "json" in content_type or response.url.endswith(".json")
                if is_jsonish and response.status < 400:
                    body_bytes = await response.body()
                    if len(body_bytes) <= MAX_RAW_BODY_BYTES:
                        try:
                            entry["body"] = json.loads(
                                body_bytes.decode("utf-8", "replace"), strict=False
                            )
                        except Exception as exc:  # noqa: BLE001
                            entry["parse_error"] = str(exc)[:200]
                responses.append(entry)
            except Exception as exc:  # noqa: BLE001
                responses.append({"url": getattr(response, "url", "?"), "capture_error": str(exc)[:200]})

        page.on("response", lambda r: pending.append(asyncio.create_task(record(r))))

        nav_error = None
        try:
            # ``wait`` is argparse-constrained to the valid literal set; cast keeps
            # mypy happy whether or not real Playwright stubs are installed.
            await page.goto(url, wait_until=cast(Any, wait), timeout=60_000)
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
        title = await page.title()
        await context.close()
        await browser.close()

    return observer.build_report(
        entry_url=url,
        page_title=title,
        nav_error=nav_error,
        wall_seconds=time.time() - started,
        responses=responses,
        html=html,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Discovery observer subprocess")
    parser.add_argument("--url", required=True)
    parser.add_argument("--scroll", type=int, default=2)
    parser.add_argument(
        "--wait", default="networkidle",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
    )
    parser.add_argument("--settle-ms", type=int, default=3000)
    args = parser.parse_args()

    report = asyncio.run(_capture(args.url, args.scroll, args.wait, args.settle_ms))
    # stdout carries ONLY the report JSON; everything else goes to stderr.
    sys.stdout.write(json.dumps(report))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
