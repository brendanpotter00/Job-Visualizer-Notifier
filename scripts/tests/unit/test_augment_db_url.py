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


def test_preserves_unrelated_query_params():
    """Existing params unrelated to keepalives (e.g. sslmode=require, which
    Railway often appends) must survive untouched. A refactor that switches
    setdefault to plain assignment would silently strip these."""
    url = "postgresql://u:p@host/db?sslmode=require&target_session_attrs=read-write"
    out = augment_db_url(url, application_name="x")
    p = _params(out)
    assert p["sslmode"] == ["require"]
    assert p["target_session_attrs"] == ["read-write"]
    # And the helper's defaults were added on top.
    assert p["keepalives"] == ["1"]
    assert p["application_name"] == ["x"]


def test_is_idempotent():
    """Calling augment_db_url on its own output is a no-op for already-set
    keys: keepalive params don't double, and the first call's
    application_name / statement_timeout win (the helper uses setdefault).

    This pins the load-bearing contract — the helper exists to prevent the
    half-open TCP hang class, and a future refactor that switches
    `params.setdefault(k, v)` to `params[k] = v` would silently override
    caller-supplied values AND double-apply on the second call. Both
    would be silent regressions that change runtime behavior without
    failing any other test.
    """
    base = "postgresql://u:p@host/db"
    out1 = augment_db_url(
        base, application_name="first", statement_timeout_ms=10_000
    )
    out2 = augment_db_url(
        out1, application_name="second", statement_timeout_ms=99_999
    )
    p = _params(out2)
    # First-call values win (setdefault semantics).
    assert p["application_name"] == ["first"]
    assert p["options"] == ["-c statement_timeout=10000"]
    # Keepalive params present and not doubled.
    for k in ("keepalives", "keepalives_idle", "keepalives_interval",
              "keepalives_count", "connect_timeout"):
        assert len(p[k]) == 1, f"{k} doubled on second call: {p[k]}"
