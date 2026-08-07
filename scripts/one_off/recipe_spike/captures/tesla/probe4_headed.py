"""Discovery probe: HEADED real Chrome vs Tesla's Akamai.

If this passes while headless failed, the block keys on headless signals
(HeadlessChrome UA / client-hint brands), not on IP.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
ENTRY = "https://www.tesla.com/careers/search/"


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="en-US")
        page = context.new_page()

        json_hits = []

        def on_response(response):
            ct = (response.headers or {}).get("content-type", "")
            url = response.url
            if ("json" in ct or "careers" in url or "cua-api" in url) and response.status < 400:
                try:
                    body = response.text()
                except Exception:
                    return
                if not body:
                    return
                hit = {"url": url[:200], "status": response.status, "bytes": len(body)}
                if "json" in ct and len(body) > 5000:
                    idx = len(list(OUT.glob("headed_raw_*.json")))
                    (OUT / f"headed_raw_{idx:02d}.json").write_text(body[:16_000_000])
                    hit["saved"] = f"headed_raw_{idx:02d}.json"
                json_hits.append(hit)

        page.on("response", on_response)
        try:
            page.goto(ENTRY, wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            print("nav error:", str(exc)[:200])
        page.wait_for_timeout(4000)
        print("TITLE:", page.title())
        print("URL after nav:", page.url)

        cookies = context.cookies()
        (OUT / "headed_cookies.json").write_text(json.dumps(cookies, indent=1))
        print("cookies:", [c["name"] for c in cookies])

        print("interesting responses:")
        for h in json_hits:
            print(" ", json.dumps(h)[:280])

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
