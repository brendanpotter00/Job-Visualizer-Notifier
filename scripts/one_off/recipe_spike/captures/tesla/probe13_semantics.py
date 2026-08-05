"""Decode the state payload's compact field names and read the site's own total."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent


def semantics() -> None:
    p = json.loads((OUT / "state_via_browser.json").read_text(), strict=False)
    deps = p["departments"]
    print("departments['3'] type:", type(deps["3"]).__name__)
    print("departments['3'] sample:", json.dumps(deps["3"])[:600])
    row = p["listings"][0]
    print("listing row:", json.dumps(row))
    print("lookup.departments['3'] =", p["lookup"]["departments"]["3"])
    print("lookup.types =", p["lookup"]["types"])
    print("lookup.locations['401022'] =", p["lookup"]["locations"]["401022"])
    # is 'f' a key inside departments[dp]?
    for dp_id, node in list(deps.items())[:3]:
        print(f"dept {dp_id} node type={type(node).__name__} sample={json.dumps(node)[:220]}")
    # field coverage
    keys = {}
    for r in p["listings"]:
        for k, v in r.items():
            keys.setdefault(k, {"nonnull": 0})
            if v is not None:
                keys[k]["nonnull"] += 1
    print("field non-null coverage over", len(p["listings"]), "rows:", json.dumps(keys))


def site_total() -> None:
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(OUT / "chrome_profile2"), channel="chrome", headless=False,
            viewport={"width": 1600, "height": 1000}, locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.tesla.com/careers/search/", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(6000)
        print("title:", page.title())
        text = page.inner_text("body")[:1500]
        print("---- visible text (head) ----")
        print(text)
        # first few job anchors
        hrefs = page.eval_on_selector_all(
            "a[href*='/careers/search/job/']", "els => els.slice(0,5).map(e => e.getAttribute('href'))"
        )
        print("job hrefs:", hrefs)
        context.close()


if __name__ == "__main__":
    semantics()
    site_total()
