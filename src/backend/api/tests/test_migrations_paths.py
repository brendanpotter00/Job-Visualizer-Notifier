"""Branch coverage for `_resolve_alembic_paths()`.

The path-resolution function has three modes:
  1. Explicit env var override (ALEMBIC_INI_PATH + ALEMBIC_SCRIPT_LOCATION).
  2. Dev layout: src/backend/api/migrations.py → repo root holds alembic.ini
     and src/backend/alembic/.
  3. Docker layout: /app/api/migrations.py → /app holds alembic.ini and
     alembic/.

Before this test file the dev branch was exercised implicitly by the rest
of the test suite, but the env-override and Docker branches were
completely untested — a regression there only surfaces at prod container
startup.

These tests monkeypatch `_HERE` (a module-level Path captured at import
time) and use tmp dirs so the function is exercised without touching the
real repo or any real env vars.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api import migrations as migrations_module
from api.migrations import _resolve_alembic_paths


class TestEnvOverride:
    def test_returns_env_paths_even_when_files_dont_exist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Explicit overrides short-circuit existence checks; the operator
        # is presumed to know what they're doing.
        ini = tmp_path / "no-such-file.ini"
        scripts = tmp_path / "no-such-dir"
        monkeypatch.setenv("ALEMBIC_INI_PATH", str(ini))
        monkeypatch.setenv("ALEMBIC_SCRIPT_LOCATION", str(scripts))

        resolved_ini, resolved_scripts = _resolve_alembic_paths()

        assert resolved_ini == ini
        assert resolved_scripts == scripts

    def test_partial_override_falls_through_to_layout_detection(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Setting only ALEMBIC_INI_PATH (without SCRIPT_LOCATION) must NOT
        # short-circuit — the function requires both. This pins the
        # `if ini_override and script_override` contract.
        monkeypatch.setenv("ALEMBIC_INI_PATH", str(tmp_path / "foo.ini"))
        monkeypatch.delenv("ALEMBIC_SCRIPT_LOCATION", raising=False)

        # Point _HERE at a tmp dir with no real files so dev/docker
        # detection falls through to FileNotFoundError. This proves the
        # half-set override didn't take effect.
        fake_here = tmp_path / "nothing" / "api" / "migrations.py"
        fake_here.parent.mkdir(parents=True)
        monkeypatch.setattr(migrations_module, "_HERE", fake_here.resolve())

        with pytest.raises(FileNotFoundError):
            _resolve_alembic_paths()


class TestDevLayout:
    def test_dev_layout_returns_repo_root_paths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Dev layout: _HERE = <root>/src/backend/api/migrations.py;
        # parents[3] = <root> holds alembic.ini and src/backend/alembic/.
        monkeypatch.delenv("ALEMBIC_INI_PATH", raising=False)
        monkeypatch.delenv("ALEMBIC_SCRIPT_LOCATION", raising=False)

        repo_root = tmp_path
        ini = repo_root / "alembic.ini"
        ini.touch()
        scripts = repo_root / "src" / "backend" / "alembic"
        scripts.mkdir(parents=True)
        fake_here = repo_root / "src" / "backend" / "api" / "migrations.py"
        fake_here.parent.mkdir(parents=True)
        monkeypatch.setattr(migrations_module, "_HERE", fake_here.resolve())

        resolved_ini, resolved_scripts = _resolve_alembic_paths()

        assert resolved_ini == ini
        assert resolved_scripts == scripts


class TestDockerLayout:
    def test_docker_layout_returns_app_root_paths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Docker layout: _HERE = /app/api/migrations.py; parents[1] = /app
        # holds alembic.ini and alembic/. Build the file tree so dev
        # detection (parents[3]) does NOT find an alembic.ini at the
        # parents[3] location, forcing fallthrough to the docker branch.
        monkeypatch.delenv("ALEMBIC_INI_PATH", raising=False)
        monkeypatch.delenv("ALEMBIC_SCRIPT_LOCATION", raising=False)

        # tmp_path/_outer1/_outer2/app/api/migrations.py: parents[3] =
        # tmp_path/_outer1/_outer2 (no alembic.ini there), parents[1] =
        # tmp_path/_outer1/_outer2/app (which holds the alembic files).
        outer1 = tmp_path / "outer1"
        outer2 = outer1 / "outer2"
        app_root = outer2 / "app"
        ini = app_root / "alembic.ini"
        scripts = app_root / "alembic"
        scripts.mkdir(parents=True)
        ini.touch()
        fake_here = app_root / "api" / "migrations.py"
        fake_here.parent.mkdir(parents=True)
        monkeypatch.setattr(migrations_module, "_HERE", fake_here.resolve())

        resolved_ini, resolved_scripts = _resolve_alembic_paths()

        assert resolved_ini == ini
        assert resolved_scripts == scripts


class TestNoLayoutAvailable:
    def test_neither_layout_nor_env_var_raises_filenotfound(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Empty tmp dir, no alembic files anywhere, no env vars set.
        # Function must raise so the failure surfaces loudly at startup
        # instead of silently passing a bogus path to alembic.
        monkeypatch.delenv("ALEMBIC_INI_PATH", raising=False)
        monkeypatch.delenv("ALEMBIC_SCRIPT_LOCATION", raising=False)

        fake_here = tmp_path / "deeply" / "nested" / "api" / "migrations.py"
        fake_here.parent.mkdir(parents=True)
        monkeypatch.setattr(migrations_module, "_HERE", fake_here.resolve())

        with pytest.raises(FileNotFoundError, match="alembic"):
            _resolve_alembic_paths()
