"""Live end-to-end data-integrity tests for the Playwright scrapers.

Each test drives a *real* scraper against the live career site (list pages
only — no detail scraping, so no per-job rate-limit delays) and asserts the
data-integrity invariants defined in ``integrity.assert_job_integrity``.

These are marked ``e2e`` and excluded from the default run (see ``pytest.ini``:
``addopts -m "not e2e"``). Run them explicitly:

    cd scripts && pytest -m e2e                # all three scrapers
    cd scripts && pytest -m e2e -k google      # just one

They require network access and a Chromium binary
(``playwright install chromium``). In CI they run on a schedule via
``.github/workflows/scraper-e2e.yml``, so a broken scraper is caught before it
skews open/closed metrics.
"""

import pytest

# Absolute package import (tests/ is a package and scripts/ is on sys.path via
# tests/conftest.py). This matches the tests/unit and tests/integration
# convention and is robust to pytest's import mode, unlike a bare
# ``from integrity import ...`` which only works under prepend mode.
from tests.e2e.integrity import SCRAPER_SPECS, assert_job_integrity


@pytest.mark.e2e
@pytest.mark.parametrize("spec", SCRAPER_SPECS, ids=lambda s: s.name)
async def test_live_scraper_data_integrity(spec):
    """Live-scrape a scraper and assert its output is healthy and well-formed."""
    scraper = spec.factory()

    # Browser lifecycle via BaseScraper.__aenter__/__aexit__. transform/filter
    # used by assert_job_integrity are pure, so we can assert after teardown.
    async with scraper:
        raw_jobs = await scraper.scrape_all_queries(max_jobs=spec.max_jobs)

    assert_job_integrity(raw_jobs, spec, scraper)
