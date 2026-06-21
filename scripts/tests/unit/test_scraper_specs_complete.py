"""Guard: the live-scraper E2E spec table must cover all three scrapers.

``tests/e2e/test_live_scrapers_e2e.py`` parametrizes one live test per entry in
``SCRAPER_SPECS``. If a spec is dropped (or the list is shrunk in a refactor),
``pytest -m e2e`` simply runs fewer cases — and a scheduled run that is green on
2 of 3 scrapers hides the third scraper's breakage, which is the exact blind spot
the E2E suite exists to close (a silently-broken scraper mass-closes its jobs via
the consecutive-misses lifecycle).

This is a cheap, network-free, NON-e2e unit test: importing ``integrity`` only
builds the spec table (dataclasses + factory lambdas). It does NOT launch a
scraper or a browser, so it belongs in (and runs in) the default suite — it must
not be marked ``e2e``.
"""

from __future__ import annotations

from shared.constants import SourceId

from tests.e2e.integrity import SCRAPER_SPECS


EXPECTED_SOURCE_IDS = {SourceId.GOOGLE, SourceId.APPLE, SourceId.MICROSOFT}


def test_exactly_three_specs() -> None:
    """All three scrapers must be specced — no silent partial coverage."""
    assert len(SCRAPER_SPECS) == 3, (
        f"expected exactly 3 scraper specs, found {len(SCRAPER_SPECS)}: "
        f"{[s.name for s in SCRAPER_SPECS]}. A shrunk SCRAPER_SPECS means "
        f"`pytest -m e2e` runs fewer live cases and a broken scraper goes "
        f"unnoticed."
    )


def test_specs_cover_all_three_source_ids() -> None:
    """The specced source_ids must be exactly Google + Apple + Microsoft."""
    source_ids = {spec.source_id for spec in SCRAPER_SPECS}
    assert source_ids == EXPECTED_SOURCE_IDS, (
        f"SCRAPER_SPECS source_ids {source_ids} != expected "
        f"{EXPECTED_SOURCE_IDS}"
    )


def test_spec_names_are_distinct() -> None:
    """Spec names must be unique (they become the parametrize test ids)."""
    names = [spec.name for spec in SCRAPER_SPECS]
    assert len(names) == len(set(names)), f"duplicate spec names: {names}"
