"""Tests for database service layer (services/database.py)."""

import json
import logging

from api.services.database import _ensure_json_string
from .conftest import _make_job, _insert_job


# --- _ensure_json_string ---

class TestEnsureJsonString:
    def test_dict_returns_json_string(self):
        result = _ensure_json_string({"key": "value"})
        assert result == json.dumps({"key": "value"})
        assert isinstance(result, str)

    def test_list_returns_json_string(self):
        result = _ensure_json_string([1, 2, 3])
        assert result == json.dumps([1, 2, 3])

    def test_none_returns_empty_object(self):
        assert _ensure_json_string(None) == "{}"

    def test_string_returned_unchanged(self):
        s = '{"already": "json"}'
        assert _ensure_json_string(s) == s

    def test_unexpected_type_returns_str_and_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _ensure_json_string(42)
        assert result == "42"
        assert "Unexpected type int" in caplog.text


# --- get_jobs with status filter (integration) ---

def test_get_jobs_filters_by_status(db_conn, test_env):
    from api.services.database import get_jobs

    _insert_job(db_conn, test_env, _make_job({"id": "status-1", "status": "OPEN"}))
    _insert_job(db_conn, test_env, _make_job({"id": "status-2", "status": "CLOSED"}))
    _insert_job(db_conn, test_env, _make_job({"id": "status-3", "status": "OPEN"}))

    open_jobs = get_jobs(db_conn, test_env, status="OPEN")
    assert len(open_jobs) == 2
    assert all(j["status"] == "OPEN" for j in open_jobs)

    closed_jobs = get_jobs(db_conn, test_env, status="CLOSED")
    assert len(closed_jobs) == 1
    assert closed_jobs[0]["id"] == "status-2"


def test_get_jobs_filters_by_company_and_status(db_conn, test_env):
    from api.services.database import get_jobs

    _insert_job(db_conn, test_env, _make_job({"id": "cs-1", "company": "google", "status": "OPEN"}))
    _insert_job(db_conn, test_env, _make_job({"id": "cs-2", "company": "google", "status": "CLOSED"}))
    _insert_job(db_conn, test_env, _make_job({"id": "cs-3", "company": "apple", "status": "OPEN"}))

    result = get_jobs(db_conn, test_env, company="google", status="OPEN")
    assert len(result) == 1
    assert result[0]["id"] == "cs-1"


def test_get_jobs_no_filter_returns_all(db_conn, test_env):
    from api.services.database import get_jobs

    _insert_job(db_conn, test_env, _make_job({"id": "nf-1", "status": "OPEN"}))
    _insert_job(db_conn, test_env, _make_job({"id": "nf-2", "status": "CLOSED"}))

    result = get_jobs(db_conn, test_env)
    assert len(result) == 2
