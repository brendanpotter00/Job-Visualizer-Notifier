"""Regression for the 2026-04-19 Railway crashloop on PR #76 deploy.

`src/backend/alembic/env.py` had a top-level
`_REPO_ROOT = Path(__file__).resolve().parents[3]` that assumed the dev
layout (env.py lives at `src/backend/alembic/env.py`, so `parents[3]` is
the repo root). In the Docker image the file lives at `/app/alembic/env.py`
— parent chain only 3 deep (`/app/alembic`, `/app`, `/`) — so `parents[3]`
raised `IndexError` at module load, crashing the FastAPI lifespan hook on
every Railway restart until the deploy was rolled back.

The fix guards the access with `if len(_HERE.parents) > 3:`. The dev branch
still prepends the repo root + `src/backend` to `sys.path`; the Docker
branch is a no-op because the Dockerfile already sets `PYTHONPATH=/app`.

Both tests execute the real env.py bootstrap (as source) in a subprocess
with `__file__` spoofed to either layout — the test fails if anyone
reintroduces an unguarded `parents[3]` access.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


def _extract_bootstrap() -> str:
    """Return env.py source from the top through the sys.path block, stopping
    before `from api.config import settings` (which would require the real
    api package to be importable in the probe subprocess).

    Strips the `from __future__ import annotations` line because the probe
    prepends a `__file__ = ...` assignment and `__future__` imports must be
    the first non-comment statement in a module. The annotations future is
    a typing convenience, not load-bearing for the sys.path guard we're
    testing."""
    src = _ENV_PY.read_text()
    # Match the import on its own line, not the occurrence inside the comment
    # above it (which references the same string in backticks).
    anchor = "\nfrom api.config import settings"
    boundary = src.find(anchor)
    assert boundary > 0, (
        "env.py no longer imports api.config at module top level — update the "
        "bootstrap boundary anchor in this test."
    )
    bootstrap = src[: boundary + 1]  # keep the trailing newline
    future_line = "from __future__ import annotations\n"
    assert future_line in bootstrap, (
        "env.py no longer has `from __future__ import annotations` — remove "
        "this strip step if it's intentionally gone."
    )
    return bootstrap.replace(future_line, "")


def _run_probe(spoofed_file: str, extra_after: str = "") -> subprocess.CompletedProcess[str]:
    bootstrap = _extract_bootstrap()
    probe_parts = [
        f"__file__ = {spoofed_file!r}",
        bootstrap,
        extra_after,
        "print('BOOTSTRAP_OK')",
    ]
    probe = "\n".join(part for part in probe_parts if part)
    return subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_docker_layout_shallow_parent_chain_does_not_raise() -> None:
    """Exact reproduction of the Railway crash. `/app/alembic/env.py` has
    `len(parents) == 3`, so the old `parents[3]` expression IndexError-ed.
    The guarded block must skip cleanly."""
    result = _run_probe("/app/alembic/env.py")
    assert result.returncode == 0, (
        "env.py bootstrap crashed under Docker-layout __file__ — "
        "this is the 2026-04-19 Railway crashloop.\n"
        f"stderr:\n{result.stderr}"
    )
    assert "BOOTSTRAP_OK" in result.stdout
    assert "IndexError" not in result.stderr


def test_dev_layout_still_prepends_repo_root_and_backend() -> None:
    """The guarded block must still run in dev so `alembic` invocations from
    the repo root or from `src/backend/` resolve `api.*` imports."""
    capture = (
        "import json\n"
        "added = [p for p in sys.path if p in (\n"
        "    '/synthetic/repo-root',\n"
        "    '/synthetic/repo-root/src/backend',\n"
        ")]\n"
        "print('ADDED_PATHS=' + json.dumps(sorted(added)))"
    )
    result = _run_probe(
        "/synthetic/repo-root/src/backend/alembic/env.py",
        extra_after=capture,
    )
    assert result.returncode == 0, result.stderr
    assert "BOOTSTRAP_OK" in result.stdout
    assert '"/synthetic/repo-root"' in result.stdout
    assert '"/synthetic/repo-root/src/backend"' in result.stdout
