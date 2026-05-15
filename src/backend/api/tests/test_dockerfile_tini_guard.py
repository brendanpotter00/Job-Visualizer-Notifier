"""
Regression guard for the tini PID-1 init/reaper line in src/backend/Dockerfile.

The 2026-05-05 scraper pthread-exhaustion incident was caused (in part) by
uvicorn running as PID 1 with no init reaper, allowing playwright/chromium
grandchildren of scraper subprocesses to accumulate as zombies against the
cgroup pids.max budget. The fix added `tini` as ENTRYPOINT so PID 1 reaps
orphans. This test pins that line in place so a future Dockerfile refactor
cannot silently delete the ENTRYPOINT (or its referenced binary) without
failing CI.

Tradeoff: this is a static text assertion, so legitimate Dockerfile
refactors (e.g., moving to a multi-stage build, switching to dumb-init)
will fail this test for non-regression reasons. We accept that — the alternative
of having no regression guard at all means the same incident can recur
silently. If the Dockerfile is intentionally restructured, update both this
test and the incident-doc reference together.

See docs/incidents/2026-05-05-scraper-pthread-exhaustion.md.
"""

from pathlib import Path

import pytest


def _resolve_dockerfile_path() -> Path:
    """Walk up from this test file to the repo's src/backend/Dockerfile.

    Layout: src/backend/api/tests/test_dockerfile_tini_guard.py
            -> parents[0] = tests/
            -> parents[1] = api/
            -> parents[2] = backend/
            => backend / 'Dockerfile' = src/backend/Dockerfile
    """
    backend_dir = Path(__file__).resolve().parents[2]
    dockerfile = backend_dir / "Dockerfile"
    assert dockerfile.exists(), f"Expected backend Dockerfile at {dockerfile}"
    return dockerfile


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    return _resolve_dockerfile_path().read_text()


def test_dockerfile_mentions_tini(dockerfile_text: str) -> None:
    """tini must be referenced somewhere in the Dockerfile (install layer
    and/or ENTRYPOINT). If this fails, the init reaper has been removed."""
    assert "tini" in dockerfile_text, (
        "Dockerfile no longer references tini. The 2026-05-05 incident "
        "(scraper pthread exhaustion) was caused by uvicorn running as "
        "PID 1 with no orphan reaper. Re-add the tini install + ENTRYPOINT, "
        "or update this test alongside an intentional restructure."
    )


def test_dockerfile_has_tini_entrypoint(dockerfile_text: str) -> None:
    """The exact ENTRYPOINT line that makes tini PID 1 must be present.
    Whitespace is normalized so a stylistic re-indent doesn't trip the test,
    but the JSON-array form is required (shell-form ENTRYPOINT defeats
    SIGTERM forwarding)."""
    expected = 'ENTRYPOINT ["/usr/bin/tini", "--"]'
    normalized_lines = [" ".join(line.split()) for line in dockerfile_text.splitlines()]
    assert expected in normalized_lines, (
        f"Dockerfile is missing the exec-form tini ENTRYPOINT line:\n"
        f"  {expected}\n"
        f"Without this, uvicorn runs as PID 1 again and the scraper-subprocess "
        f"orphan-reap path is gone. See "
        f"docs/incidents/2026-05-05-scraper-pthread-exhaustion.md."
    )


def test_dockerfile_keeps_uvicorn_cmd(dockerfile_text: str) -> None:
    """Defensive: catch the 'oops, deleted CMD too' scenario. The uvicorn
    CMD must still be present so tini has something to exec as PID 2."""
    normalized = " ".join(dockerfile_text.split())
    # Match the JSON-array CMD with uvicorn as argv[0]; tolerate whitespace
    # variance inside the array.
    assert 'CMD [ "uvicorn"' in normalized or 'CMD ["uvicorn"' in normalized, (
        "Dockerfile no longer has a `CMD [\"uvicorn\", ...]` line. tini "
        "needs a child command to exec; without CMD, the container would "
        "exit immediately."
    )


def test_dockerfile_installs_tini(dockerfile_text: str) -> None:
    """The `apt-get install ... tini` line must be present. Guards a
    regression mode the existing tests miss: if a future refactor deletes
    the install layer but leaves the ENTRYPOINT line dangling, the build
    would fail at runtime with `exec /usr/bin/tini: no such file or
    directory`. The other tests (substring 'tini' check, ENTRYPOINT line
    check) would both still pass — neither distinguishes the install line
    from the ENTRYPOINT line.

    We whitespace-normalize each line then check for both 'apt-get install'
    and 'tini' tokens within the same line so a stylistic re-indent or
    line-continuation rearrangement still matches.
    """
    normalized_lines = [" ".join(line.split()) for line in dockerfile_text.splitlines()]
    matching = [
        line for line in normalized_lines
        if "apt-get install" in line and "tini" in line
    ]
    assert matching, (
        "Dockerfile is missing an `apt-get install ... tini` line. The "
        "ENTRYPOINT references /usr/bin/tini, so without an install layer "
        "the build would produce an image that crashes immediately on "
        "exec. See docs/incidents/2026-05-05-scraper-pthread-exhaustion.md."
    )


def test_dockerfile_sets_pythonunbuffered(dockerfile_text: str) -> None:
    """`ENV PYTHONUNBUFFERED=1` must be present so the scraper subprocess
    flushes stderr/stdout per-write instead of in 4 KB blocks. Without
    this, a hung scraper subprocess never emits log lines before SIGKILL
    and Railway logs go silent for 90 minutes — the exact failure mode
    the appleScraperHangFix observability work was added to fix. See
    docs/implementations/appleScraperHangFix/PLAN.md.
    """
    expected = "ENV PYTHONUNBUFFERED=1"
    normalized_lines = [" ".join(line.split()) for line in dockerfile_text.splitlines()]
    assert expected in normalized_lines, (
        f"Dockerfile is missing the `{expected}` line. Without it Python "
        "block-buffers stderr when piped to the parent runner, and the "
        "scraper goes silent in Railway logs whenever it hangs."
    )
