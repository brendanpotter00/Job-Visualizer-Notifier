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

from shared.constants import SourceId

# Absolute package import (tests/ is a package and scripts/ is on sys.path via
# tests/conftest.py). This matches the tests/unit and tests/integration
# convention and is robust to pytest's import mode, unlike a bare
# ``from integrity import ...`` which only works under prepend mode.
from tests.e2e.integrity import SCRAPER_SPECS, assert_job_integrity


# Exactly the three scrapers the live E2E suite must always exercise.
_EXPECTED_SOURCE_IDS = {SourceId.GOOGLE, SourceId.APPLE, SourceId.MICROSOFT}


@pytest.mark.e2e
def test_specs_present():
    """Fail the scheduled ``-m e2e`` job if not all three scrapers are specced.

    This guard is marked ``e2e`` ON PURPOSE — that is the whole point. The
    scheduled workflow (``.github/workflows/scraper-e2e.yml``) runs only
    ``pytest -m e2e``. ``test_live_scraper_data_integrity`` is parametrized over
    ``SCRAPER_SPECS``, so if that list is empty the parametrize set is empty and
    pytest SKIPs the case (``empty parameter set``) → exit 0 (GREEN); if it
    shrinks to 2 entries only 2 cases run → exit 0 (GREEN). In either case the
    scheduled run goes green WITHOUT having exercised all three scrapers — the
    exact silent partial-coverage blind spot this suite exists to close.

    The companion ``tests/unit/test_scraper_specs_complete.py`` already protects
    PR CI (it is NOT marked ``e2e`` and runs in the default suite). This is the
    defense-in-depth twin for the SCHEDULED job: marked ``e2e`` so it is
    COLLECTED (never deselected) under ``-m e2e``, guaranteeing the scheduled run
    goes RED if ``SCRAPER_SPECS`` is empty or partial. It is network-free and
    browser-free — it only inspects the in-memory spec table — so it never adds
    flakiness.
    """
    assert len(SCRAPER_SPECS) == 3, (
        f"expected exactly 3 scraper specs, found {len(SCRAPER_SPECS)}: "
        f"{[s.name for s in SCRAPER_SPECS]}. With fewer than 3, `pytest -m e2e` "
        f"runs fewer (or zero) live cases yet still exits 0 — a green scheduled "
        f"run would NOT prove all three scrapers ran."
    )
    source_ids = {spec.source_id for spec in SCRAPER_SPECS}
    assert source_ids == _EXPECTED_SOURCE_IDS, (
        f"SCRAPER_SPECS source_ids {source_ids} != expected "
        f"{_EXPECTED_SOURCE_IDS} — every scheduled run must exercise exactly "
        f"Google + Apple + Microsoft."
    )


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
