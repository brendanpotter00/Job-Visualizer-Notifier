"""pytest fixtures for the enricher-cutover section (PLAN.md §2, §3).

No stack, no ports, no network: every case builds its own throwaway "machine"
(``cutover_sandbox.Sandbox``) in its tmp dir and runs the REAL cutover/watcher
scripts against it. Fixtures:

* ``host``        — the real uv / git / Python 3.12 the sandboxes borrow (session).
* ``scripts_src`` — a copy of ``src/enricher/scripts/{cutover,lib}`` under test
                    (``$E2E_CUTOVER_SRC`` overrides, to prove the cases bite).
* ``make_sandbox``— builds a sandbox; tears it down (kills its processes, copies
                    its evidence into ``cases/<test>/``) after the case.
* ``step``        — ``step("what I am doing")``; ``cases/<test>/step.txt`` names
                    the last step, for a PASS as well as a FAIL.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

import pytest

_HERE = Path(__file__).resolve()
_SECTION_DIR = _HERE.parents[1]
if str(_SECTION_DIR) not in sys.path:
    sys.path.insert(0, str(_SECTION_DIR))

import cutover_sandbox as cs  # noqa: E402

ARTIFACTS_DIR = Path(os.environ.get(
    "E2E_ARTIFACTS_DIR", str(_SECTION_DIR / "artifacts" / f"local-{int(time.time())}")))
CASES_DIR = ARTIFACTS_DIR / "cases"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "fast: cheap cases (`--fast`)")
    CASES_DIR.mkdir(parents=True, exist_ok=True)


# --- step tracking + step.txt ----------------------------------------------

_CURRENT_STEP: dict[str, str] = {}


@pytest.fixture()
def step(request: pytest.FixtureRequest) -> Callable[[str], None]:
    def _set(text: str) -> None:
        _CURRENT_STEP[request.node.nodeid] = text
        print(f"  [step] {text}", flush=True)

    _set("setting up")
    return _set


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    d = CASES_DIR / _sanitize(item.name)
    where = _CURRENT_STEP.get(item.nodeid, "(no step recorded)")
    if report.failed:
        d.mkdir(parents=True, exist_ok=True)
        (d / "step.txt").write_text(
            f"FAILED ({report.when}) while: {where}\n\n{report.longrepr}\n", encoding="utf-8")
    elif report.when == "call" and report.passed:
        d.mkdir(parents=True, exist_ok=True)
        (d / "step.txt").write_text(f"PASS — last step: {where}\n", encoding="utf-8")


@pytest.fixture()
def case_dir(request: pytest.FixtureRequest) -> Path:
    d = CASES_DIR / _sanitize(request.node.name)
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- the sandbox ------------------------------------------------------------


@pytest.fixture(scope="session")
def host() -> cs.Host:
    try:
        return cs.Host()
    except cs.SandboxError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture(scope="session")
def scripts_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return cs.copy_scripts_under_test(tmp_path_factory.mktemp("scripts-under-test"))


def _teardown(sb: cs.Sandbox, dest: Path) -> None:
    sb.kill_everything()
    time.sleep(0.2)
    sb.collect(dest)
    left = sb.leftover_processes()
    if left:
        sb.kill_everything()
        (dest / "leftover-processes.txt").write_text("\n".join(left) + "\n")


@pytest.fixture()
def make_sandbox(host: cs.Host, scripts_src: Path, tmp_path: Path,
                 case_dir: Path) -> Iterator[Callable[..., cs.Sandbox]]:
    made: list[cs.Sandbox] = []

    def _make(*, real_tag: str | None = None, interval_s: float = 1.0, **build) -> cs.Sandbox:
        sb = cs.Sandbox(tmp_path / f"sb{len(made)}", host, scripts_src,
                        real_tag=real_tag, interval_s=interval_s)
        made.append(sb)
        return sb.build(**build)

    yield _make
    for i, sb in enumerate(made):
        _teardown(sb, case_dir / (f"sandbox{i}" if len(made) > 1 else "sandbox"))


@pytest.fixture(scope="module")
def module_sandbox(host: cs.Host, scripts_src: Path, tmp_path_factory: pytest.TempPathFactory,
                   request: pytest.FixtureRequest) -> Iterator[Callable[..., cs.Sandbox]]:
    """One sandbox shared by a module's cases (CO-01 / CO-14 / CO-15 inspect the
    same happy-path run)."""
    made: list[cs.Sandbox] = []
    name = _sanitize(Path(str(request.node.fspath)).stem)

    def _make(**build) -> cs.Sandbox:
        if not made:
            sb = cs.Sandbox(tmp_path_factory.mktemp(name), host, scripts_src)
            made.append(sb)
            sb.build(**build)
        return made[0]

    yield _make
    for sb in made:
        _teardown(sb, CASES_DIR / f"{name}-shared-sandbox")
