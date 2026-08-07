"""Complete the evidence matrix.

1) How many listings does the plain-HTTP-reachable www.tesla.cn state hold?
2) Bundled Playwright Chromium, HEADED vs HEADLESS, fresh context —
   headless is exactly what replay.run_browser_dom does.
"""
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def cn_counts() -> None:
    with httpx.Client(timeout=25) as client:
        r = client.get("https://www.tesla.cn/cua-api/apps/careers/state", headers={"User-Agent": UA})
    payload = json.loads(r.text, strict=False)
    (OUT / "state_cn.json").write_text(r.text)
    listings = payload.get("listings", [])
    print(f"tesla.cn state: status={r.status_code} listings={len(listings)}")
    print("  sites:", payload.get("lookup", {}).get("sites"))
    print("  sample:", json.dumps(listings[0]) if listings else "none")

    glob = json.loads((OUT / "state_via_browser.json").read_text(), strict=False)
    print(f"tesla.com state (browser-obtained): listings={len(glob.get('listings', []))}")
    cn_ids = {x["id"] for x in listings}
    glob_ids = {x["id"] for x in glob.get("listings", [])}
    print(f"  cn ids also present globally: {len(cn_ids & glob_ids)} / {len(cn_ids)}")
    print(f"  coverage of global set: {100 * len(cn_ids & glob_ids) / max(len(glob_ids), 1):.1f}%")


def bundled(headless: bool) -> None:
    label = f"bundled-chromium-{'headless' if headless else 'headed'}"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, locale="en-US", user_agent=UA
        )
        page = context.new_page()
        state_bytes = {}

        def on_response(response):
            if "cua-api/apps/careers/state" in response.url and response.status < 400:
                try:
                    state_bytes["n"] = len(response.text())
                except Exception:
                    pass

        page.on("response", on_response)
        try:
            page.goto("https://www.tesla.com/careers/search/", wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            print(f"{label}: nav error {str(exc)[:120]}")
        page.wait_for_timeout(5000)
        print(f"{label}: title={page.title()!r} state_bytes={state_bytes.get('n')}")
        context.close()
        browser.close()


if __name__ == "__main__":
    cn_counts()
    bundled(headless=True)
    bundled(headless=False)
