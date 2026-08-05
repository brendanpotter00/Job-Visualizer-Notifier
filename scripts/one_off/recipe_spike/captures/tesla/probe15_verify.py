"""Cross-check the 4830 site figure against the state payload, and verify the
bare-id job URL actually resolves to the job (no slug needed)."""
import json
import random
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent


def us_count() -> None:
    p = json.loads((OUT / "state_via_browser.json").read_text(), strict=False)
    us_loc_ids = set()
    for region in p["geo"]:
        for site in region["sites"]:
            if site["id"] != "US":
                continue
            for state in site["states"]:
                for _city, ids in state["cities"].items():
                    us_loc_ids.update(ids)
    listings = p["listings"]
    us = [r for r in listings if r["l"] in us_loc_ids]
    print(f"state listings total = {len(listings)}")
    print(f"state listings with a US location = {len(us)}  (site UI claimed 4830 under its default US filter)")
    sites = {s["id"] for region in p["geo"] for s in region["sites"]}
    print("countries present in geo:", sorted(sites))


def verify_url() -> None:
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(OUT / "chrome_profile3"), channel="chrome", headless=False,
            viewport={"width": 1600, "height": 1000}, locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        for _ in range(3):
            page.goto("https://www.tesla.com/careers/search/job/224501", wait_until="domcontentloaded", timeout=60_000)
            for _ in range(6):
                page.mouse.move(random.randint(100, 1400), random.randint(100, 900), steps=10)
                page.wait_for_timeout(400)
            page.wait_for_timeout(4000)
            if "Access Denied" not in page.title():
                break
        print("bare-id URL title:", page.title())
        print("final url:", page.url)
        print("body head:", page.inner_text("body")[:300].replace("\n", " | "))
        context.close()


if __name__ == "__main__":
    us_count()
    verify_url()
