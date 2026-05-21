"""Unit tests for ``scripts.shared.database.augment_db_url``."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from scripts.shared.database import augment_db_url


def _params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query, keep_blank_values=True)


def test_adds_keepalives_and_application_name():
    url = "postgresql://u:p@host:5432/db"
    out = augment_db_url(url, application_name="procrastinate_worker")
    p = _params(out)
    assert p["keepalives"] == ["1"]
    assert p["keepalives_idle"] == ["30"]
    assert p["keepalives_interval"] == ["10"]
    assert p["keepalives_count"] == ["3"]
    assert p["connect_timeout"] == ["10"]
    assert p["application_name"] == ["procrastinate_worker"]
    assert "options" not in p


def test_statement_timeout_uses_options_kwarg():
    out = augment_db_url(
        "postgresql://u:p@host/db",
        application_name="x",
        statement_timeout_ms=60_000,
    )
    p = _params(out)
    assert p["options"] == ["-c statement_timeout=60000"]


def test_caller_supplied_params_win():
    # An incoming URL with explicit application_name/connect_timeout must
    # not be overridden by the helper's defaults.
    url = (
        "postgresql://u:p@host/db"
        "?application_name=custom&connect_timeout=99&keepalives=0"
    )
    out = augment_db_url(url, application_name="ignored")
    p = _params(out)
    assert p["application_name"] == ["custom"]
    assert p["connect_timeout"] == ["99"]
    assert p["keepalives"] == ["0"]
    # Other defaults still added
    assert p["keepalives_idle"] == ["30"]


def test_rejects_non_postgresql_scheme():
    with pytest.raises(ValueError, match="Unsupported database scheme"):
        augment_db_url("mysql://u:p@host/db", application_name="x")


def test_preserves_userinfo_and_path():
    url = "postgresql://user:secret@db.example.com:5432/jobscraper"
    out = augment_db_url(url, application_name="x")
    parsed = urlparse(out)
    assert parsed.username == "user"
    assert parsed.password == "secret"
    assert parsed.hostname == "db.example.com"
    assert parsed.port == 5432
    assert parsed.path == "/jobscraper"
