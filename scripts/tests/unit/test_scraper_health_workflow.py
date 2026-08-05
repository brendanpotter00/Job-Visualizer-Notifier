"""Guard: the daily scraper-health workflow must stay wired up.

Mirrors ``test_pytest_config_excludes_e2e.py`` — a cheap, no-network,
no-database check that a piece of *configuration* the codebase depends on
hasn't silently rotted.

``.github/workflows/scraper-health.yml`` IS the alerting for dead scrapers.
There is no PagerDuty and no third-party monitor: the whole mechanism is
"a scheduled Action fails, GitHub emails the repo owner." That makes three
things load-bearing, and all three are easy to break without noticing:

1. the ``schedule:`` trigger — drop it and the workflow only runs when
   someone remembers to click it, which is never;
2. ``curl -f`` — without it, a 401 (rotated key) or a 502 (backend down)
   returns an HTML error page with exit code 0, and the check goes GREEN
   against a backend that is completely unreachable;
3. ``jq -e`` on ``staleCount`` — without ``-e``, jq prints ``false`` and
   exits 0, so every stale scraper passes.

A broken alert is silent by definition, so none of these fail loudly on
their own. Hence this test.

Parsing note: PyYAML is NOT a dependency of this repo and this guard is not
worth adding one for, so the assertions are deliberately textual (the same
spirit as the ``configparser``/stdlib-only sibling guard). The one piece of
structure that matters — that ``schedule:`` sits under the top-level
``on:`` block — is checked by walking indentation rather than by a full
YAML parse.
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "scraper-health.yml"
CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _top_level_on_block(text: str) -> list[str]:
    """Return the lines of the top-level ``on:`` block (excluding the header).

    A top-level key is one at column 0. Everything indented under ``on:``
    until the next column-0 line belongs to the block.
    """
    lines = text.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines) if re.fullmatch(r"on:\s*", line)
        )
    except StopIteration:  # pragma: no cover - asserted by the caller
        return []

    block: list[str] = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return block


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), (
        f"{WORKFLOW} is missing — the daily dead-scraper alert is the only "
        "alerting this project has."
    )
    return WORKFLOW.read_text()


def test_workflow_file_exists_and_is_non_empty(workflow_text: str) -> None:
    assert workflow_text.strip()
    assert workflow_text.startswith("name:")


def test_workflow_is_manual_only(workflow_text: str) -> None:
    """Pins the 2026-08-05 owner decision: daily alerting is owned by the
    scraper-health-watch LaunchAgent (scripts/health_watch/), not a second
    scheduled channel. This workflow stays as an on-demand probe only — a
    ``schedule:`` trigger reappearing here would false-fail daily until the
    JVN_BACKEND_URL / JVN_INTERNAL_API_KEY repo secrets are added, so its
    return must be a deliberate choice, not rebase drift.
    """
    block = _top_level_on_block(workflow_text)
    assert block, "scraper-health.yml has no top-level `on:` block"

    joined = "\n".join(block)
    assert not re.search(r"^\s+schedule:\s*$", joined, re.MULTILINE), (
        "scraper-health.yml must NOT have a `schedule:` trigger — daily "
        "alerting is owned by the scraper-health-watch LaunchAgent; "
        "re-adding cron requires the repo secrets and an explicit decision"
    )
    assert re.search(r"^\s+workflow_dispatch:\s*$", joined, re.MULTILINE), (
        "keep workflow_dispatch so the check can be run on demand while "
        "debugging a dead scraper"
    )


def test_curl_fails_hard_on_http_errors(workflow_text: str) -> None:
    """``curl -f`` is what turns a 401/502 into a red run.

    Without it curl exits 0 on an error status and hands jq an HTML body —
    the step then fails for a confusing reason, or (worse, if the jq
    assertion is ever made lenient) passes against an unreachable backend.
    """
    assert "curl -fsS" in workflow_text, (
        "the scraper-health curl must use -f (as `curl -fsS`) so an HTTP "
        "error status fails the step"
    )


def test_staleness_assertion_uses_jq_dash_e(workflow_text: str) -> None:
    """``jq -e`` is what turns ``staleCount > 0`` into a failing exit code."""
    assert "jq -e '.staleCount == 0'" in workflow_text, (
        "the workflow must assert `jq -e '.staleCount == 0'` — plain `jq` "
        "prints `false` and exits 0, so stale scrapers would pass"
    )


def test_prints_the_stale_list_before_failing(workflow_text: str) -> None:
    """The failure email/log must name the dead companies, otherwise the
    owner has to go re-run something by hand to learn anything."""
    jq_e_at = workflow_text.index("jq -e '.staleCount == 0'")
    assert ".stale[]" in workflow_text[:jq_e_at], (
        "the workflow must print the `.stale[]` entries BEFORE the failing "
        "jq -e assertion"
    )


def test_calls_the_scraper_health_endpoint_with_the_internal_key(
    workflow_text: str,
) -> None:
    assert "/api/jobs-qa/scraper-health" in workflow_text
    assert "X-Internal-Key" in workflow_text
    assert "secrets.JVN_INTERNAL_API_KEY" in workflow_text
    assert "secrets.JVN_BACKEND_URL" in workflow_text


def test_is_not_part_of_pr_blocking_ci(workflow_text: str) -> None:
    """This hits a live external system; its result reflects production
    health, not the correctness of the diff under review. It must never gate
    merges (same reasoning as scraper-e2e.yml)."""
    assert "scraper-health" not in CI_WORKFLOW.read_text(), (
        "scraper-health must not be invoked from PR-blocking CI"
    )
    joined = "\n".join(_top_level_on_block(workflow_text))
    assert "pull_request" not in joined
    assert not re.search(r"^\s+push:\s*$", joined, re.MULTILINE)
