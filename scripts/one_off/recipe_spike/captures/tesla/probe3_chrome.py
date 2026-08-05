"""Discovery probe: real branded Chrome (channel='chrome') vs Tesla's Akamai.

Also fetches the careers state API from inside the page context and dumps
cookies so we can test whether cookie-armed httpx would pass.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
ENTRY = "https://www.tesla.com/careers/search/"


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="en-US")
        page = context.new_page()

        json_hits = []

        def on_response(response):
            ct = (response.headers or {}).get("content-type", "")
            if "json" in ct and response.status < 400:
                try:
                    body = response.text()
                except Exception:
                    return
                json_hits.append({"url": response.url, "status": response.status, "bytes": len(body)})
                if len(body) > 5000:  # only save substantial payloads
                    idx = len(list(OUT.glob("chrome_raw_*.json")))
                    (OUT / f"chrome_raw_{idx:02d}.json").write_text(body[:8_000_000])
                    json_hits[-1]["saved"] = f"chrome_raw_{idx:02d}.json"

        page.on("response", on_response)
        try:
            page.goto(ENTRY, wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            print("nav error:", str(exc)[:200])
        page.wait_for_timeout(3000)
        print("TITLE:", page.title())
        print("URL after nav:", page.url)

        # try the state API from inside the page (browser TLS + cookies)
        try:
            status = page.evaluate(
                """async () => {
                    const r = await fetch('/cua-api/apps/careers/state', {credentials: 'include'});
                    const t = await r.text();
                    return {status: r.status, bytes: t.length, head: t.slice(0, 200)};
                }"""
            )
            print("in-page fetch /cua-api/apps/careers/state:", json.dumps(status)[:400])
        except Exception as exc:
            print("in-page fetch error:", str(exc)[:200])

        cookies = context.cookies()
        (OUT / "chrome_cookies.json").write_text(json.dumps(cookies, indent=1))
        print("cookies:", [c["name"] for c in cookies])

        print("JSON responses seen:")
        for h in json_hits:
            print(" ", json.dumps(h)[:300])

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
