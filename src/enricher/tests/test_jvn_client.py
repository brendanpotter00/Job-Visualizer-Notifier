import logging

from job_enricher.jvn_client import JVNClient


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeHttp:
    def __init__(self, data):
        self._data = data
        self.closed = False

    def get(self, url, params=None, headers=None):
        return _FakeResp(self._data)

    def close(self):
        self.closed = True


def test_pull_pending_skips_malformed_rows():
    """E5/E10: a row missing both job_id/id, and a row with an empty source_id,
    are skipped instead of aborting the whole batch."""
    data = {
        "jobs": [
            {"job_id": "1", "source_id": "greenhouse", "title": "ok"},
            {"title": "no id at all"},                       # E5 — missing job id
            {"job_id": "3", "source_id": "", "title": "empty source"},  # E10
        ],
        "enabled": True,
    }
    c = JVNClient(base_url="http://x", internal_key="k")
    rows = c.pull_pending(client=_FakeHttp(data))
    assert [r["job_listing_id"] for r in rows] == ["1"]


def test_pull_pending_skips_non_dict_element():
    """E17: a non-dict jobs[] element (string/None) is skipped, not crashing the
    whole batch with AttributeError; the valid dict rows still come back."""
    data = {
        "jobs": [
            {"job_id": "1", "source_id": "greenhouse", "title": "ok"},
            "i am not a dict",                                # E17 — non-dict
            None,                                             # E17 — non-dict
            {"job_id": "2", "source_id": "greenhouse", "title": "ok2"},
        ],
        "enabled": True,
    }
    c = JVNClient(base_url="http://x", internal_key="k")
    rows = c.pull_pending(client=_FakeHttp(data))
    assert [r["job_listing_id"] for r in rows] == ["1", "2"]


def test_pull_pending_reads_disabled_flag(caplog):
    """E12: enabled=false is surfaced distinctly (logged) from an empty queue."""
    c = JVNClient(base_url="http://x", internal_key="k")
    with caplog.at_level(logging.WARNING, logger="job_enricher.jvn_client"):
        rows = c.pull_pending(client=_FakeHttp({"jobs": [], "enabled": False}))
    assert rows == []
    assert any("disabl" in r.getMessage().lower() for r in caplog.records)


def test_to_inbox_row_missing_both_ids_is_tolerant():
    # no KeyError — job_listing_id comes back falsy so pull_pending can skip it
    row = JVNClient._to_inbox_row({"title": "orphan"})
    assert not row["job_listing_id"]


def test_to_inbox_row_maps_fields():
    row = JVNClient._to_inbox_row({
        "job_id": "abc", "source_id": "greenhouse", "title": "SWE", "company": "acme",
        "location": "SF", "description_html": "<p>x</p>", "details": {"department": "Eng"},
    })
    assert row["job_listing_id"] == "abc"
    assert row["raw_location"] == "SF"
    assert row["content_hash"]
    assert '"department"' in row["details_json"]


def test_to_inbox_row_id_fallback_and_description_fallback():
    row = JVNClient._to_inbox_row({"id": "x", "description": "plain text"})
    assert row["job_listing_id"] == "x"
    assert row["description_html"] == "plain text"


def test_headers_require_key(monkeypatch):
    import pytest
    # The constructor falls back to settings.internal_api_key when internal_key is
    # None, so a populated .env.local / INTERNAL_API_KEY would mask the guard. Null
    # the singleton to assert "no key configured" raises regardless of ambient config.
    monkeypatch.setattr("job_enricher.jvn_client.settings.internal_api_key", None)
    c = JVNClient(base_url="http://x", internal_key=None)
    with pytest.raises(RuntimeError):
        c._headers()


def test_url_join():
    c = JVNClient(base_url="http://x/", internal_key="k")
    assert c._url("pending") == "http://x/api/internal/enrichment/pending"


class _CaptureHttp:
    """Fake httpx.Client capturing get/post calls; returns scripted data."""

    def __init__(self, data):
        self._data = data
        self.gets = []
        self.posts = []

    def get(self, url, params=None, headers=None):
        self.gets.append((url, params, headers))
        return _FakeResp(self._data)

    def post(self, url, content=None, headers=None):
        self.posts.append((url, content, headers))
        return _FakeResp(self._data)

    def close(self):
        pass


def test_post_metrics_hits_metrics_endpoint():
    c = JVNClient(base_url="http://x", internal_key="k")
    http = _CaptureHttp({"ok": True})
    out = c.post_metrics({"tick_uuid": "u-1", "counters": {}}, client=http)
    assert out == {"ok": True}
    url, content, headers = http.posts[0]
    assert url == "http://x/api/internal/enrichment/metrics"
    assert '"tick_uuid": "u-1"' in content
    assert headers["X-Internal-Key"] == "k"


def test_get_corrections_parses_and_passes_params():
    data = {
        "corrections": [
            {"job_listing_id": "1", "source_id": "greenhouse", "title": "SWE",
             "company": "acme", "category": "software_engineering", "level": "mid",
             "tags": ["python"], "corrected_at": "2026-07-01T00:00:00Z"},
            "not-a-dict",  # malformed element dropped, not crashing
        ],
        "count": 1,
    }
    c = JVNClient(base_url="http://x", internal_key="k")
    http = _CaptureHttp(data)
    rows = c.get_corrections(since="2026-06-01T00:00:00Z", limit=50, client=http)
    assert len(rows) == 1 and rows[0]["job_listing_id"] == "1"
    url, params, headers = http.gets[0]
    assert url == "http://x/api/internal/enrichment/corrections"
    assert params == {"since": "2026-06-01T00:00:00Z", "limit": 50}
