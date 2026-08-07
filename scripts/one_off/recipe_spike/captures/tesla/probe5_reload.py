"""Discovery probe: headed Chrome + persistent profile + reload after sensor.

Akamai Bot Manager validates _abck after sensor POSTs; a reload then often
passes. Tests page reload and in-page API fetch.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
PROFILE = OUT / "chrome_profile"
ENTRY = "https://www.tesla.com/careers/search/"


def main() -> None:
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE),
            channel="chrome",
            headless=False,
            viewport={"width": 1600, "height": 1000},
            locale="en-US",
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
                    idx = len(list(OUT.glob("reload_raw_*.json")))
                    (OUT / f"reload_raw_{idx:02d}.json").write_text(body[:16_000_000])
                    saved.append({"url": response.url[:220], "bytes": len(body), "file": f"reload_raw_{idx:02d}.json"})

        page.on("response", on_response)

        for attempt in range(3):
            try:
                page.goto(ENTRY, wait_until="networkidle", timeout=60_000)
            except Exception as exc:
                print(f"attempt {attempt}: nav error {str(exc)[:150]}")
            page.wait_for_timeout(6000)
            title = page.title()
            abck = next((c["value"] for c in context.cookies() if c["name"] == "_abck"), "")
            print(f"attempt {attempt}: title={title!r} abck_valid_marker={'~0~' in abck}")
            if "Access Denied" not in title:
                break

        # in-page fetch of the state API regardless
        try:
            result = page.evaluate(
                """async () => {
                    const r = await fetch('/cua-api/apps/careers/state', {credentials: 'include'});
                    const t = await r.text();
                    return {status: r.status, bytes: t.length, head: t.slice(0, 150)};
                }"""
            )
            print("in-page fetch state:", json.dumps(result)[:400])
        except Exception as exc:
            print("in-page fetch error:", str(exc)[:200])

        print("saved payloads:", json.dumps(saved, indent=1))
        (OUT / "reload_cookies.json").write_text(json.dumps(context.cookies(), indent=1))
        context.close()


if __name__ == "__main__":
    main()
