"""Read the site's own claimed job total (headed real Chrome + mouse activity)."""
import json
import random
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent


def main() -> None:
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(OUT / "chrome_profile3"), channel="chrome", headless=False,
            viewport={"width": 1600, "height": 1000}, locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        for attempt in range(3):
            page.goto("https://www.tesla.com/careers/search/", wait_until="domcontentloaded", timeout=60_000)
            for _ in range(8):
                page.mouse.move(random.randint(100, 1400), random.randint(100, 900), steps=random.randint(5, 20))
                page.wait_for_timeout(random.randint(250, 700))
            page.wait_for_timeout(5000)
            if "Access Denied" not in page.title():
                break
            print(f"attempt {attempt}: blocked")
        print("title:", page.title())
        body = page.inner_text("body")
        (OUT / "careers_page_text.txt").write_text(body)
        head = body[:1200]
        print("---- visible text (head) ----")
        print(head)
        nums = re.findall(r"([\d,]{3,})\s*(?:Open\s+)?(?:Positions|Jobs|Results|results)", body)
        print("count-like matches:", nums[:10])
        hrefs = page.eval_on_selector_all(
            "a[href*='/careers/search/job/']", "els => els.slice(0,5).map(e => e.getAttribute('href'))"
        )
        print("job hrefs:", hrefs)
        (OUT / "careers_page_rendered.html").write_text(page.content()[:3_000_000])
        context.close()


if __name__ == "__main__":
    main()
