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
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
PYTEST_INI = SCRIPTS_DIR / "pytest.ini"


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


def test_strict_markers_enabled(pytest_ini: configparser.ConfigParser) -> None:
    """``--strict-markers`` must be on so a typo'd/unregistered marker (e.g. a
    dropped or misspelled ``@pytest.mark.e2e``) becomes a hard collection error
    instead of a silently-ignored warning that lets live tests rejoin the run."""
    addopts = pytest_ini.get("pytest", "addopts", fallback="")
    assert "--strict-markers" in addopts, (
        "scripts/pytest.ini addopts must contain --strict-markers so an "
        "unregistered marker fails collection rather than being ignored"
    )


def test_default_collection_excludes_live_e2e_tests() -> None:
    """Behavioral guard: the *actual* default collection must contain zero tests
    under ``tests/e2e/``.

    The string-only checks above can stay green even if ``@pytest.mark.e2e`` is
    dropped from the live test — the marker stays registered and ``addopts``
    stays intact, yet the live browser tests silently rejoin the default
    ``cd scripts && pytest`` run (PR CI). This runs the real default collection
    (no ``-m`` override) in a subprocess and asserts no e2e node id is collected,
    so it fails loudly the moment the marker is removed/typo'd.

    Network-free and fast: ``--collect-only`` imports modules but launches no
    browser and hits no site.
    """
    # ``--no-header -p no:cacheprovider`` keep the run hermetic. We must NOT pass
    # ``-o addopts=...`` or ``-m``: the whole point is to exercise pytest.ini's
    # *own* default ``-m "not e2e"`` exclusion, not a re-stated one. Because
    # addopts carries ``-v``, collection prints the tree format
    # (``<Module test_live_scrapers_e2e.py>`` / ``<Coroutine ...>``) rather than
    # flat ``tests/e2e/...`` node ids, so the leak check below matches on both
    # the path fragment AND the live-test identifiers that survive either format.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=SCRIPTS_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # exit code 5 = "no tests collected"; anything that broke collection (2/3/4)
    # is a real failure we want to surface, not swallow.
    assert result.returncode in (0, 5), (
        "default `pytest --collect-only` did not complete cleanly "
        f"(exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )

    # The live e2e tests are uniquely identifiable by their path
    # (``tests/e2e/``), their module (``test_live_scrapers_e2e``), and their
    # function (``test_live_scraper_data_integrity``). Matching any of these
    # catches a leak whether pytest prints flat node ids or the verbose tree.
    e2e_signals = (
        "tests/e2e/",
        "tests\\e2e\\",
        "test_live_scrapers_e2e",
        "test_live_scraper_data_integrity",
    )
    leaked = [
        line
        for line in result.stdout.splitlines()
        if any(sig in line for sig in e2e_signals)
    ]
    assert not leaked, (
        "the default test run (no -m) collected live e2e tests — the "
        "`@pytest.mark.e2e` marker was likely dropped or typo'd, so browser "
        "tests would run in PR CI. Offending collection lines:\n"
        + "\n".join(leaked)
    )
