"""Real-DOM pin of Apple's pagination markup, through a real Playwright engine.

This is the faithful half of the 2026-08-28 incident regression suite. It loads
Apple's ACTUAL captured pagination HTML (verified live on 2026-08-31) into a real
Chromium page via ``set_content`` and runs the production selectors against it —
so it exercises Playwright's real ``:has-text`` / attribute matching, which a
mocked page cannot. It is network-free (no live site), hence deterministic and
non-flaky, but it needs a browser binary, so it is marked ``e2e`` and runs in
``.github/workflows/scraper-e2e.yml`` (``pytest -m e2e``), not in default CI.

The unit-level, browser-free contract test is
``tests/unit/test_apple_pagination_markup.py``.

See docs/incidents/2026-08-28-apple-pagination-single-page.md.
"""

import pytest
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.parser import check_has_next_page, get_total_pages


# Captured live from https://jobs.apple.com/en-us/search?location=united-states-USA
# on 2026-08-31. The "Next" button is an icon-only chevron: empty text, label in
# aria-label. On a middle page it is enabled; on the last page Apple sets BOTH
# disabled="" and aria-disabled="true" (the Previous arrow shows the same
# disabled encoding on page 1, quoted here so the pin captures it too).
_NAV_TEMPLATE = """
<!doctype html><html><body>
<nav class="rc-pagination" aria-label="Results pagination" id="search-pagnation">
  <div>
    <div class="rc-pagination-arrow">
      <button class="icon icon-chevronstart" type="button" disabled=""
              aria-label="Previous Page" aria-disabled="true"
              data-analytics-pagination="prev"></button>
    </div>
    <div class="rc-pagination-spacing" id="current-page-label">
      <input id="pagination-search-page-number" type="number" value="{page}">
      <div><span class="rc-pagination-delimiter">Of</span>
        <span class="rc-pagination-total-pages" data-autom="paginationTotalPages">226</span>
      </div>
    </div>
    <div class="rc-pagination-arrow">
      <button class="icon icon-chevronend" type="button" aria-label="Next Page"
              {next_disabled} data-analytics-pagination="next"></button>
    </div>
  </div>
</nav>
</body></html>
"""

MIDDLE_PAGE_HTML = _NAV_TEMPLATE.format(page=1, next_disabled="")
LAST_PAGE_HTML = _NAV_TEMPLATE.format(
    page=226, next_disabled='disabled="" aria-disabled="true"'
)


@pytest.mark.e2e
async def test_apple_pagination_markup_pins_fix_and_root_cause():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()

            # ---- middle page: Next is present and enabled ----
            await page.set_content(MIDDLE_PAGE_HTML)

            # ROOT-CAUSE PIN: the old text-content selector finds NOTHING against
            # Apple's real markup (the button's textContent is empty). This is
            # exactly why the scraper stopped after page 1.
            assert await page.query_selector('button:has-text("Next Page")') is None

            # The fix, run through the real selector engine, keeps paginating.
            assert await check_has_next_page(page) is True
            assert await get_total_pages(page) == 226

            # ---- last page: Next is disabled="" + aria-disabled="true" ----
            await page.set_content(LAST_PAGE_HTML)
            assert await check_has_next_page(page) is False
            assert await get_total_pages(page) == 226
        finally:
            await browser.close()
