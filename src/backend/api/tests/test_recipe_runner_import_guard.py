"""E7 Phase 3a — the load-bearing proof that the REPLAY path is agent-free.

Three independent guards (invariant #5, "a proof, not a convention"):

1. **Runtime (subprocess):** import the runner in a *fresh* interpreter and assert
   none of the forbidden modules landed in that process's ``sys.modules``.
2. **Static (AST):** walk the runner's whole first-party import closure AND every
   ``tasks/`` module reachable from the custom-company leaf task, asserting no
   ``import``/``from`` of a forbidden package — catching a transitive import a
   runtime probe would miss when a branch is not exercised.
3. **The live check:** ``assert_no_agent_imports`` fires if an agent leaks in, and
   ``playwright`` is in the forbidden set (HTTP-only replay).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from api.services.recipe_runner import FORBIDDEN_MODULES, assert_no_agent_imports

_BACKEND = Path(__file__).resolve().parents[2]          # src/backend
_API = _BACKEND / "api"
_RUNNER = _API / "services" / "recipe_runner.py"
_LEAF_TASK = _API / "tasks" / "fetch_custom_company.py"
_REPO_ROOT = _BACKEND.parents[1]            # worktree/repo root (holds scripts/)

# The subprocess import checks must resolve BOTH ``api`` (under src/backend) and
# ``scripts`` (at the repo root, imported transitively by procrastinate_app),
# regardless of how pytest was invoked. Pin PYTHONPATH explicitly rather than
# relying on an inherited one, so the guard proves the boundary — not the env.
_SUBPROC_ENV = {**os.environ, "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(_BACKEND)])}


# --- 1. runtime subprocess check --------------------------------------------

def test_subprocess_import_leaves_no_forbidden_module() -> None:
    code = (
        "import sys\n"
        "import api.services.recipe_runner as r\n"
        "leaked = sorted(m for m in r.FORBIDDEN_MODULES if m in sys.modules)\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    leaked = result.stdout.strip()
    assert leaked == "", f"forbidden modules leaked on import: {leaked!r}"


def test_importing_the_task_package_leaves_no_browser_driver_resident() -> None:
    """E7 Phase 3b boundary: importing the whole ``tasks`` package (which now
    imports the discovery leaf task, and thus the discovery package) must NOT leave
    a browser driver resident — the observer runs Playwright OUT OF PROCESS, so the
    replay leaf task's per-call runtime guard stays satisfied in the same worker.

    ``anthropic`` is deliberately NOT asserted absent: the shared worker already
    hosts location-normalization, which loads it, and the runtime guard tolerates
    that (see ``recipe_runner._RUNTIME_FORBIDDEN_MODULES``). Only the discovery-only
    browser drivers are a decidable proof of contamination."""
    code = (
        "import sys\n"
        "import api.tasks  # imports every task, including the discovery leaf task\n"
        "import api.tasks.fetch_custom_company  # the agent-free replay leaf task\n"
        "browser = sorted(m for m in ('playwright', 'stagehand', 'browserbase', 'langchain')\n"
        "                 if m in sys.modules)\n"
        "print(','.join(browser))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    leaked = result.stdout.strip()
    assert leaked == "", f"a discovery browser driver leaked into the worker: {leaked!r}"


# --- 2. AST walk ------------------------------------------------------------

def _module_name_for(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(_BACKEND).with_suffix("")
    except ValueError:
        return path.stem  # a file outside src/backend (e.g. the meta-test's tmp file)
    return ".".join(rel.parts)


def _imports_and_targets(path: Path) -> tuple[set[str], list[Path]]:
    """Return (top-level absolute import names, resolvable first-party target files)."""
    tree = ast.parse(path.read_text(), filename=str(path))
    self_mod = _module_name_for(path)
    top_names: set[str] = set()
    targets: list[Path] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_names.add(alias.name.split(".")[0])
                targets.extend(_resolve(alias.name, 0, self_mod))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                top_names.add(node.module.split(".")[0])
            targets.extend(_resolve(node.module or "", node.level, self_mod))
    return top_names, targets


def _resolve(module: str, level: int, self_mod: str) -> list[Path]:
    """Resolve an import to candidate first-party .py files under src/backend."""
    if level > 0:
        base_parts = self_mod.split(".")[:-level] if level <= len(self_mod.split(".")) else []
        dotted = ".".join([*base_parts, *(module.split(".") if module else [])])
    else:
        dotted = module
    if not dotted.startswith("api."):
        return []
    rel = Path(*dotted.split("."))
    out: list[Path] = []
    for cand in (_BACKEND / rel.with_suffix(".py"), _BACKEND / rel / "__init__.py"):
        if cand.exists():
            out.append(cand)
    return out


def _closure(seed: Path, *, confine_to: Path | None) -> set[Path]:
    """BFS the first-party import graph from ``seed``; only recurse into files under
    ``confine_to`` (whole ``api/`` if None). Returns every visited file."""
    seen: set[Path] = set()
    queue = [seed]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        _, targets = _imports_and_targets(current)
        for target in targets:
            if target in seen:
                continue
            if confine_to is not None and confine_to not in target.parents:
                continue  # e.g. don't descend from tasks/ into services/llm_client
            queue.append(target)
    return seen


def test_replay_path_closure_has_no_forbidden_import() -> None:
    """The runner's ENTIRE first-party closure (recipe_runner + recipe_schema +
    harvest_meta …) imports nothing forbidden — transitively."""
    for module_file in _closure(_RUNNER, confine_to=_API):
        top_names, _ = _imports_and_targets(module_file)
        offending = top_names & set(FORBIDDEN_MODULES)
        assert not offending, f"{module_file} imports forbidden {offending}"


def test_leaf_task_tasks_closure_has_no_forbidden_import() -> None:
    """Every ``tasks/`` module reachable from the custom-company leaf task imports
    nothing forbidden. Confined to tasks/ so the walk does not descend into the
    (legitimately anthropic-using) services layer — a leaf task itself must never
    reach for an agent."""
    tasks_dir = _API / "tasks"
    closure = _closure(_LEAF_TASK, confine_to=tasks_dir)
    assert _LEAF_TASK in closure
    for module_file in closure:
        top_names, _ = _imports_and_targets(module_file)
        offending = top_names & set(FORBIDDEN_MODULES)
        assert not offending, f"{module_file} imports forbidden {offending}"


def test_browser_agent_stagehand_is_subprocess_isolated() -> None:
    """E7 Stagehand pivot boundary: ``_stagehand_main`` is the SOLE importer of
    ``stagehand``/``browserbase``, and the in-process modules (``runner``/``discover``/
    ``schema``/``__init__``) reach NEITHER — transitively (closure confined to api/) —
    NOR ``_stagehand_main`` itself. This is the AST proof behind the subprocess design:
    importing the package never makes a browser/agent driver resident in the worker."""
    ba_dir = _API / "services" / "browser_agent"
    main = ba_dir / "_stagehand_main.py"

    main_names, _ = _imports_and_targets(main)
    assert "stagehand" in main_names, "_stagehand_main must import stagehand (the sole importer)"

    for entry in ("runner.py", "discover.py", "schema.py", "__init__.py"):
        closure = _closure(ba_dir / entry, confine_to=_API)
        assert main not in closure, (
            f"{entry} transitively imports _stagehand_main — stagehand would leak into the worker"
        )
        for module_file in closure:
            top_names, _ = _imports_and_targets(module_file)
            offending = top_names & {"stagehand", "browserbase"}
            assert not offending, f"{module_file} imports agent driver {offending}"


def test_ast_guard_would_catch_a_planted_forbidden_import(tmp_path: Path) -> None:
    """Meta-test: the AST walk actually detects a forbidden import (so a green run
    means something)."""
    planted = tmp_path / "evil.py"
    planted.write_text("import playwright\nfrom anthropic import Anthropic\n")
    top_names, _ = _imports_and_targets(planted)
    assert {"playwright", "anthropic"} <= top_names
    assert top_names & set(FORBIDDEN_MODULES)


# --- 3. the live guard + the forbidden set ----------------------------------

def test_playwright_is_forbidden() -> None:
    """HTTP-only replay: a browser driver on this path is as forbidden as an LLM."""
    for name in ("anthropic", "openai", "stagehand", "browserbase", "langchain", "playwright"):
        assert name in FORBIDDEN_MODULES


def test_assert_no_agent_imports_fires_on_a_browser_driver_leak() -> None:
    """The per-call runtime guard fires when a discovery-only browser driver leaks
    into the process. (It deliberately does NOT fire on anthropic — the shared
    worker co-hosts location-normalization, which loads anthropic legitimately; the
    static subprocess + AST guards above are what prove the replay CODE cannot reach
    an LLM regardless of co-tenancy.)"""
    assert assert_no_agent_imports() is None
    sys.modules["playwright"] = object()  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="browser/agent driver"):
            assert_no_agent_imports()
    finally:
        del sys.modules["playwright"]


def test_runtime_guard_tolerates_a_co_resident_llm_sdk() -> None:
    """anthropic being resident (the shared worker co-hosts normalization) must NOT
    trip the per-call guard — else every production replay would raise. The static
    guards keep anthropic in the FORBIDDEN set; the runtime guard scopes narrower."""
    already = "anthropic" in sys.modules
    sys.modules.setdefault("anthropic", object())  # type: ignore[arg-type]
    try:
        assert assert_no_agent_imports() is None
    finally:
        if not already:
            del sys.modules["anthropic"]
