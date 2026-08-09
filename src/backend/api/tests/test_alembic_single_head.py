"""Guard: the Alembic revision graph must always have exactly ONE head.

Why this test exists
--------------------
`api/migrations.py::apply_alembic_migrations` runs `command.upgrade(cfg, "head")`
— **singular** — inside the FastAPI lifespan, and re-raises on failure. If the
version graph ever has two heads, Alembic raises
`Multiple head revisions are present for given argument 'head'` and the backend
**crashes on boot**. On Railway that is a deploy-time outage, not a warning, and
it is only discovered after the merge that created the second head is already on
`main`.

Two heads are easy to create by accident and invisible in a diff: two branches
authored in parallel each set `down_revision` to the same parent, both look fine
in review, and the graph only forks at merge time. That is exactly what happened
on 2026-07-13 — `a3c32c2aa4d3` (job_freshness re-sync) and `5ee285a3c724`
(experience_level / is_remote_eligible columns) were both written against parent
`01fef5c9c582` during the same outage response. See
`docs/incidents/2026-07-13-api-jobs-outage.md`.

This test is deliberately **DB-free**: it reads the revision files off disk via
`ScriptDirectory` and never opens a connection, so it runs in the plain
`cd src/backend && pytest` step (and in CI) with no Postgres and no
`TEST_DATABASE_URL`. It fails at review time on the branch that would fork the
graph, which is the only cheap moment to catch it.

Fixing a failure: do NOT hand-write a new revision and do NOT use
`alembic merge` (no precedent in this repo — history here is strictly linear).
Re-parent the newer revision's `down_revision` onto the current head.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# Path resolution mirrors the sibling Alembic tests (test_alembic_env_docker_layout.py):
# this file is src/backend/api/tests/test_alembic_single_head.py, so
# parents[2] is src/backend (which holds alembic/) and parents[4] is the repo
# root (which holds alembic.ini).
_HERE = Path(__file__).resolve()
_SRC_BACKEND = _HERE.parents[2]
_REPO_ROOT = _HERE.parents[4]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _SRC_BACKEND / "alembic"


def _script_directory() -> ScriptDirectory:
    """Load the revision graph from disk — no database URL required.

    `script_location` in alembic.ini is relative to the repo root, but backend
    pytest runs from `src/backend/`, so it is overridden with an absolute path
    exactly as `api/migrations.py` does.
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    # alembic.ini carries [loggers]/[handlers] sections; env.py's fileConfig
    # branch would reset the root logger and clobber pytest's caplog handlers.
    # ScriptDirectory never executes env.py, but clear this for symmetry with
    # api/migrations.py so the two configs can't drift.
    cfg.config_file_name = None
    return ScriptDirectory.from_config(cfg)


def test_alembic_has_exactly_one_head() -> None:
    heads = _script_directory().get_heads()

    assert len(heads) == 1, (
        f"Alembic revision graph has {len(heads)} heads: {sorted(heads)}. "
        "api/migrations.py runs `command.upgrade(cfg, 'head')` (singular) in "
        "the FastAPI lifespan, so more than one head crashes the backend on "
        "boot. Re-parent the newer revision's `down_revision` onto the current "
        "head — do not use `alembic merge` (no precedent in this repo)."
    )


def test_every_revision_is_reachable_from_the_head() -> None:
    """Nothing is orphaned: walking down from the head visits every revision.

    A single head is necessary but not sufficient — a revision whose
    `down_revision` points at a deleted or misspelled id would be an
    unreachable island that `upgrade head` silently never runs.
    """
    script = _script_directory()
    (head,) = script.get_heads()

    reachable = {rev.revision for rev in script.walk_revisions("base", head)}
    all_revisions = {rev.revision for rev in script.walk_revisions()}

    assert reachable == all_revisions, (
        "Alembic revisions unreachable from the head: "
        f"{sorted(all_revisions - reachable)}. Every revision must sit on the "
        "single linear chain from base to head."
    )
