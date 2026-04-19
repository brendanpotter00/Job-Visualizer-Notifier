"""Mismatch-guard coverage for `apply_alembic_migrations(database_url, env)`.

`env.py` computes the version-table suffix from
`api.config.settings.scraper_environment`, which is bound at module import
time from SCRAPER_ENVIRONMENT (default "local"). A caller passing env="prod"
while settings is still "local" would silently migrate alembic_version_local
against a prod DB.

Pass 1 of review added a guard that compared `os.environ["SCRAPER_ENVIRONMENT"]`
to `env`. That missed the "env var unset → settings defaulted to local"
path. Pass 2 tightened the guard to compare against settings directly; this
file locks in that contract.
"""

from __future__ import annotations

import importlib

import pytest

from api import config as api_config
from api.migrations import apply_alembic_migrations


class TestEnvMismatchGuard:
    def test_raises_when_settings_env_differs_from_arg(self, monkeypatch):
        """settings.scraper_environment='local', arg='prod' → must raise."""
        monkeypatch.setattr(api_config.settings, "scraper_environment", "local")
        with pytest.raises(RuntimeError, match="scraper_environment mismatch"):
            apply_alembic_migrations("postgresql://unused/db", "prod")

    def test_raises_when_env_var_unset_but_arg_is_prod(self, monkeypatch):
        """Env var unset → settings defaults to 'local'. Arg='prod' must raise.

        This is the specific footgun the Pass 1 guard missed: it only checked
        os.environ, so a None env var silently fell through while settings
        still carried the 'local' default.
        """
        monkeypatch.delenv("SCRAPER_ENVIRONMENT", raising=False)
        monkeypatch.setattr(api_config.settings, "scraper_environment", "local")
        with pytest.raises(RuntimeError, match="scraper_environment mismatch"):
            apply_alembic_migrations("postgresql://unused/db", "prod")

    def test_raises_when_env_var_unset_but_arg_is_qa(self, monkeypatch):
        monkeypatch.delenv("SCRAPER_ENVIRONMENT", raising=False)
        monkeypatch.setattr(api_config.settings, "scraper_environment", "local")
        with pytest.raises(RuntimeError, match="scraper_environment mismatch"):
            apply_alembic_migrations("postgresql://unused/db", "qa")

    def test_does_not_raise_when_settings_matches_arg(self, monkeypatch):
        """settings.scraper_environment='prod', arg='prod' → guard passes.

        The function will then hit Alembic and fail for a different reason
        (the DB URL is fake), which we tolerate — we're only asserting the
        guard lets matched calls through.
        """
        monkeypatch.setattr(api_config.settings, "scraper_environment", "prod")
        with pytest.raises(Exception) as excinfo:
            apply_alembic_migrations("postgresql://unused/db", "prod")
        assert "scraper_environment mismatch" not in str(excinfo.value)

    def test_error_message_names_both_sides(self, monkeypatch):
        """Message must cite both settings-side and arg-side values so
        operators can diagnose which one is wrong."""
        monkeypatch.setattr(api_config.settings, "scraper_environment", "local")
        with pytest.raises(RuntimeError) as excinfo:
            apply_alembic_migrations("postgresql://unused/db", "prod")
        msg = str(excinfo.value)
        assert "'local'" in msg
        assert "'prod'" in msg
        assert "alembic_version_local" in msg
