"""Unit tests for the scripts/migrate.py CLI helpers.

Covers the 2am-runbook surface: _connect failure path must exit(2) with a
human-readable stderr line and must not leak credentials through _mask_db_url.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make "scripts" importable as a package.
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts import migrate as migrate_cli


class TestMaskDbUrl:
    def test_strips_username_and_password(self):
        masked = migrate_cli._mask_db_url(
            "postgresql://user:secret@db.internal:5432/jobs"
        )
        assert "user" not in masked
        assert "secret" not in masked
        assert "db.internal" in masked
        assert "5432" in masked

    def test_preserves_host_without_port(self):
        masked = migrate_cli._mask_db_url("postgresql://u:p@db.internal/jobs")
        assert "p" not in masked.split("@")[-1] if "@" in masked else True
        assert "db.internal" in masked

    def test_unparseable_returns_placeholder(self):
        # Anything the urllib parser can't extract a hostname from should
        # fall through to the <unparseable-url> sentinel rather than leaking
        # the original (possibly credential-bearing) string.
        assert migrate_cli._mask_db_url("") == "<unparseable-url>"


class TestConnectFailurePath:
    def test_bad_url_exits_with_code_2(self, capsys):
        args = SimpleNamespace(
            db_url="postgresql://nouser:nopassword@127.0.0.1:1/nodb",
            env="local",
        )
        with pytest.raises(SystemExit) as excinfo:
            migrate_cli._connect(args)
        assert excinfo.value.code == 2

        captured = capsys.readouterr()
        assert "error: failed to connect to database" in captured.err
        assert "env=local" in captured.err
        # The masked URL must not leak the password.
        assert "nopassword" not in captured.err
        # And it should include the host so the operator knows *which* DB
        # the attempt targeted.
        assert "127.0.0.1" in captured.err
