"""Guard: the live ``e2e`` scrapers must stay out of the default test run.

The whole point of marking the live scraper tests ``e2e`` and adding
``-m "not e2e"`` to ``addopts`` is that the PR-blocking CI step
(``cd scripts && pytest`` in ``.github/workflows/ci.yml``) never launches a
browser or hits a live site — those tests run only on the scheduled
``scraper-e2e.yml`` workflow via ``pytest -m e2e``.

If a future edit drops the exclusion (or unregisters the marker), browser tests
would silently start running in PR CI and flake merges. These cheap, no-network
tests fail loudly if that invariant regresses.
"""

import configparser
from pathlib import Path

import pytest

PYTEST_INI = Path(__file__).resolve().parents[2] / "pytest.ini"


@pytest.fixture(scope="module")
def pytest_ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI)
    return parser


def test_addopts_excludes_e2e_by_default(pytest_ini: configparser.ConfigParser) -> None:
    """Default runs must deselect the live ``e2e`` marker."""
    addopts = pytest_ini.get("pytest", "addopts", fallback="")
    assert 'not e2e' in addopts, (
        "scripts/pytest.ini addopts must contain -m \"not e2e\" so the default "
        "`pytest` run (PR CI) excludes the live browser scraper tests"
    )


def test_e2e_marker_is_registered(pytest_ini: configparser.ConfigParser) -> None:
    """The ``e2e`` marker must be declared (no unknown-marker warnings/errors)."""
    markers = pytest_ini.get("pytest", "markers", fallback="")
    assert any(line.strip().startswith("e2e") for line in markers.splitlines()), (
        "scripts/pytest.ini must register the `e2e` marker under [pytest] markers"
    )
