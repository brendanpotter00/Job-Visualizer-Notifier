"""Discovery probe: headed real Chrome + AutomationControlled disabled + human-ish input.

Goal: get Akamai's _abck to validate. If content loads, capture the jobs
payload URL and test cookie transplant to httpx.
"""
import json
import random
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
PROFILE = OUT / "chrome_profile2"
ENTRY = "https://www.tesla.com/careers/search/"


def main() -> None:
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE),
            channel="chrome",
            headless=False,
            viewport={"width": 1600, "height": 1000},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        saved = []

        def on_response(response):
            ct = (response.headers or {}).get("content-type", "")
            if "json" in ct and response.status < 400:
                try:
                    body = response.text()
                except Exception:
                    return
                if len(body) > 5000:
                    idx = len(list(OUT.glob("stealth_raw_*.json")))
                    (OUT / f"stealth_raw_{idx:02d}.json").write_text(body[:16_000_000])
                    saved.append({"url": response.url[:220], "bytes": len(body), "file": f"stealth_raw_{idx:02d}.json"})

        page.on("response", on_response)

        for attempt in range(3):
            try:
                page.goto(ENTRY, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                print(f"attempt {attempt}: nav error {str(exc)[:150]}")
            # human-ish behavior for the sensor
            for _ in range(6):
                page.mouse.move(random.randint(100, 1400), random.randint(100, 900), steps=random.randint(5, 20))
                page.wait_for_timeout(random.randint(300, 800))
            page.mouse.wheel(0, 600)
            page.wait_for_timeout(5000)
            title = page.title()
            abck = next((c["value"] for c in context.cookies() if c["name"] == "_abck"), "")
            webdriver_flag = page.evaluate("navigator.webdriver")
            print(f"attempt {attempt}: title={title!r} webdriver={webdriver_flag} abck_valid={'~0~' in abck}")
            if "Access Denied" not in title:
                break

        try:
            result = page.evaluate(
                """async () => {
                    const r = await fetch('/cua-api/apps/careers/state', {credentials: 'include'});
                    const t = await r.text();
                    return {status: r.status, bytes: t.length, head: t.slice(0, 150)};
                }"""
            )
            print("in-page fetch state:", json.dumps(result)[:400])
            if result.get("status") == 200:
                blob = page.evaluate(
                    "async () => (await fetch('/cua-api/apps/careers/state', {credentials:'include'})).text()"
                )
                (OUT / "state_via_browser.json").write_text(blob)
                print("saved state_via_browser.json bytes:", len(blob))
        except Exception as exc:
            print("in-page fetch error:", str(exc)[:200])

        print("saved payloads:", json.dumps(saved, indent=1))
        (OUT / "stealth_cookies.json").write_text(json.dumps(context.cookies(), indent=1))
        context.close()


if __name__ == "__main__":
    main()
