"""Cookie transplant test: earn Akamai trust in headed Chrome, replay via httpx.

Determines whether replay.py's HTTP stack (httpx, HTTP/1.1) could ever fetch
the state endpoint using recipe-baked cookies, and verifies the job URL shape.
"""
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
PROFILE = OUT / "chrome_profile2"
ENTRY = "https://www.tesla.com/careers/search/"
STATE = "https://www.tesla.com/cua-api/apps/careers/state"


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
        page.goto(ENTRY, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)
        title = page.title()
        ua = page.evaluate("navigator.userAgent")
        print("title:", title)
        print("real UA:", ua)

        # verify job detail URL pattern
        try:
            probe = page.evaluate(
                """async () => {
                    const r = await fetch('/careers/search/job/224501', {redirect: 'follow'});
                    return {status: r.status, finalUrl: r.url};
                }"""
            )
            print("job url probe /careers/search/job/224501:", json.dumps(probe))
        except Exception as exc:
            print("job url probe error:", str(exc)[:200])

        cookies = context.cookies("https://www.tesla.com")
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        print("cookie names:", [c["name"] for c in cookies])
        context.close()

    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.tesla.com/careers/search/",
        "Cookie": cookie_header,
    }
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        r = client.get(STATE, headers=headers)
    print(f"httpx-with-cookies: status={r.status_code} bytes={len(r.content)}")
    if r.status_code == 200:
        payload = json.loads(r.text, strict=False)
        print("  listings:", len(payload.get("listings", [])))
        (OUT / "state_via_httpx.json").write_text(r.text)


if __name__ == "__main__":
    main()
