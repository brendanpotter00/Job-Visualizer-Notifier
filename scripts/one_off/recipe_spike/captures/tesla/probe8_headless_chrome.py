"""Boundary test: real Chrome in NEW HEADLESS mode vs Tesla's Akamai.

Case A: fresh profile (what a cron replay faces from scratch).
Case B: pre-trusted persistent profile (chrome_profile2, validated earlier).
Both with --disable-blink-features=AutomationControlled and UA override to
mask 'HeadlessChrome'.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
ENTRY = "https://www.tesla.com/careers/search/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


def attempt(pw, label: str, profile: str | None):
    args = ["--disable-blink-features=AutomationControlled"]
    if profile:
        context = pw.chromium.launch_persistent_context(
            profile, channel="chrome", headless=True, locale="en-US",
            viewport={"width": 1600, "height": 1000}, user_agent=UA, args=args,
        )
        page = context.pages[0] if context.pages else context.new_page()
        browser = None
    else:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=args)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000}, locale="en-US", user_agent=UA
        )
        page = context.new_page()

    state_hit = {}

    def on_response(response):
        if "cua-api/apps/careers/state" in response.url and response.status < 400:
            try:
                state_hit["bytes"] = len(response.text())
            except Exception:
                pass

    page.on("response", on_response)
    try:
        page.goto(ENTRY, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        print(f"{label}: nav error {str(exc)[:150]}")
    for _ in range(5):
        page.mouse.move(400, 400, steps=10)
        page.wait_for_timeout(600)
    page.wait_for_timeout(5000)
    abck = next((c["value"] for c in context.cookies() if c["name"] == "_abck"), "")
    print(f"{label}: title={page.title()!r} abck_valid={'~0~' in abck} state_bytes={state_hit.get('bytes')}")
    try:
        r = page.evaluate(
            "async () => { const r = await fetch('/cua-api/apps/careers/state', {credentials:'include'}); return r.status; }"
        )
        print(f"{label}: in-page state fetch status={r}")
    except Exception as exc:
        print(f"{label}: in-page fetch error {str(exc)[:150]}")
    context.close()
    if browser:
        browser.close()


def main() -> None:
    with sync_playwright() as pw:
        attempt(pw, "A-fresh-headless", None)
        attempt(pw, "B-trusted-headless", str(OUT / "chrome_profile2"))


if __name__ == "__main__":
    main()
