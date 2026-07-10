"""Write-back path tests — the seam that carries CR-1/CR-2 and the E1/E2/E7
fixes, plus the composite failed[] matching, the 5xx/429 transient retry
taxonomy, warnings[] logging, and the poison-row attempts lifecycle.

Uses a fake JVNClient (no network, no httpx transport) whose `post_results`
returns JVN's real `{"written", "failed", "warnings"}` shape or raises httpx
errors.
"""

import argparse
import json
import logging

import httpx
import pytest

from job_enricher import cli
from job_enricher.writeback import write_back


# ---- fakes -----------------------------------------------------------------
class FakeClient:
    """post_results returns scripted outcomes; each call captures its payload.

    An outcome may be a dict (returned), or an Exception (raised). Once the
    script is exhausted it falls back to a clean all-written response.
    """

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = []  # list[list[dict]] — one entry per post_results call

    def post_results(self, payload):
        self.calls.append([dict(item) for item in payload])
        outcome = self.script.pop(0) if self.script else {"written": len(payload), "failed": []}
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _http_status_error(code=400):
    req = httpx.Request("POST", "http://jvn.local/api/internal/enrichment/results")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"{code}", request=req, response=resp)


def _seed(store, jid, conf=0.9, reasoning="why", category="software_engineering",
          level="senior", source_id="greenhouse"):
    store.enqueue_inbox([{
        "job_listing_id": jid, "source_id": source_id, "title": "SWE",
        "company": "acme", "raw_location": "SF", "description_html": "<p>x</p>",
        "details_json": None, "content_hash": "h" + jid + source_id,
    }])
    store.record_clean(source_id, jid, "clean text for " + jid)
    store.record_enrichment({
        "job_listing_id": jid, "source_id": source_id,
        "category": category, "level": level,
        "level_includes": json.dumps([level]), "tags": json.dumps(["backend"]),
        "locations": json.dumps([]), "classify_confidence": conf,
        "classify_reasoning": reasoning, "taxonomy_version": "v1+abc",
    })


# ---- E1: honor JVN failed[] ------------------------------------------------
def test_partial_failure_marks_only_written_sent(store):
    _seed(store, "1")
    _seed(store, "2")
    client = FakeClient(script=[{"written": 1, "failed": [{"job_listing_id": "2", "error": "boom"}]}])

    res = write_back(store, client=client, batch_size=10)

    assert res["sent"] == 1
    assert res["failed"] == 1
    assert res["unsent"] == 1
    # row 1 written -> sent; row 2 rejected -> still unsent for next tick
    still_unsent = [r["job_listing_id"] for r in store.enriched_unsent()]
    assert still_unsent == ["2"]
    # poison-row lifecycle: the rejection bumped the attempts counter
    with store.connect() as c:
        assert c.execute("SELECT attempts FROM inbox WHERE job_listing_id='2'").fetchone()["attempts"] == 1


def test_failed_entry_with_source_id_matches_exact_pair(store):
    """failed[] entries carrying source_id resolve on the composite pair even
    when two batch rows share the bare id."""
    _seed(store, "X", source_id="src-a")
    _seed(store, "X", source_id="src-b")
    client = FakeClient(script=[{
        "written": 1,
        "failed": [{"job_listing_id": "X", "source_id": "src-b", "error": "bad"}],
    }])

    res = write_back(store, client=client, batch_size=10)

    assert res["sent"] == 1 and res["failed"] == 1
    left = [(r["source_id"], r["job_listing_id"]) for r in store.enriched_unsent()]
    assert left == [("src-b", "X")]


def test_failed_entry_without_source_id_ambiguous_leaves_all_unsent(store):
    """A source-less failed[] entry whose bare id matches TWO batch rows is
    ambiguous: neither row is marked sent (no guessing), attempts NOT bumped."""
    _seed(store, "X", source_id="src-a")
    _seed(store, "X", source_id="src-b")
    client = FakeClient(script=[{
        "written": 1,
        "failed": [{"job_listing_id": "X", "error": "bad"}],
    }])

    res = write_back(store, client=client, batch_size=10)

    assert res["sent"] == 0
    assert res["unsent"] == 2
    with store.connect() as c:
        attempts = [r["attempts"] for r in c.execute("SELECT attempts FROM inbox").fetchall()]
    assert attempts == [0, 0]  # can't know which row JVN rejected


def test_rejected_row_goes_terminal_failed_after_max_attempts(store):
    """After MAX_WRITEBACK_ATTEMPTS rejections the row turns status='failed'
    and stops being offered to write-back — no more per-tick error noise."""
    _seed(store, "1")
    reject = {"written": 0, "failed": [{"job_listing_id": "1", "source_id": "greenhouse", "error": "poison"}]}
    for _ in range(5):
        res = write_back(store, client=FakeClient(script=[reject]), batch_size=10)
        assert res["failed"] == 1
    assert store.enriched_unsent() == []  # terminal — excluded
    res = write_back(store, client=FakeClient(), batch_size=10)
    assert res == {"sent": 0, "batches": 0, "retries": 0, "failed": 0, "unsent": 0, "errors": 0}
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox WHERE job_listing_id='1'").fetchone()["status"] == "failed"


# ---- warnings[] logging ------------------------------------------------------
def test_warnings_are_logged_and_rows_still_sent(store, caplog):
    _seed(store, "1")
    client = FakeClient(script=[{
        "written": 1, "failed": [],
        "warnings": [{"job_listing_id": "1", "source_id": "greenhouse",
                      "warnings": ["skipped: human-corrected"]}],
    }])
    with caplog.at_level(logging.WARNING, logger="job_enricher.writeback"):
        res = write_back(store, client=client, batch_size=10)
    assert res["sent"] == 1  # written=counted even when intentionally not applied
    assert any("human-corrected" in r.getMessage() for r in caplog.records)


# ---- E3 (CR-2): classify fields are emitted --------------------------------
def test_posted_item_includes_classify_confidence_and_reasoning(store):
    _seed(store, "1", conf=0.42, reasoning="decisive title signal")
    client = FakeClient()

    write_back(store, client=client, batch_size=10)

    item = client.calls[0][0]
    assert item["classify_confidence"] == 0.42
    assert item["classify_reasoning"] == "decisive title signal"
    # clean_description + raw_location ride along from the inbox join
    assert item["clean_description"] == "clean text for 1"
    assert item["raw_location"] == "SF"


# ---- retry semantics -------------------------------------------------------
def test_transient_error_then_success(store):
    _seed(store, "1")
    sleeps = []
    client = FakeClient(script=[httpx.ConnectError("flaky"), {"written": 1, "failed": []}])

    res = write_back(store, client=client, batch_size=10, sleep=sleeps.append)

    assert res["sent"] == 1
    assert res["unsent"] == 0
    assert res["retries"] == 1
    assert sleeps == [1]  # backoff 2**0 after the first transient failure
    assert store.enriched_unsent() == []


def test_all_retries_fail_leaves_unsent_and_signals_error(store):
    store.start_tick()
    _seed(store, "1")
    client = FakeClient(script=[httpx.ConnectError("down")] * 3)

    res = write_back(store, client=client, batch_size=10, sleep=lambda s: None, max_retries=3)

    assert res["sent"] == 0
    assert res["unsent"] == 1
    assert res["errors"] == 1
    assert len(client.calls) == 3  # exhausted the retries
    assert len(store.enriched_unsent()) == 1
    # E7: the tick errors counter is bumped by the unsent-row count
    assert store.latest_tick()["errors"] == 1


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_5xx_and_429_are_transient_and_retried(store, code):
    """A Railway-restart 502 (or rate-limit 429) must retry with backoff, not
    abort the batch."""
    _seed(store, "1")
    sleeps = []
    client = FakeClient(script=[_http_status_error(code), {"written": 1, "failed": []}])

    res = write_back(store, client=client, batch_size=10, sleep=sleeps.append)

    assert res["sent"] == 1
    assert res["retries"] == 1
    assert sleeps == [1]
    assert len(client.calls) == 2


def test_5xx_exhaustion_leaves_rows_unsent(store):
    _seed(store, "1")
    client = FakeClient(script=[_http_status_error(503)] * 3)

    res = write_back(store, client=client, batch_size=10, sleep=lambda s: None, max_retries=3)

    assert res["sent"] == 0
    assert res["unsent"] == 1
    assert len(client.calls) == 3


def test_non_transient_error_does_not_burn_retries(store):
    _seed(store, "1")
    client = FakeClient(script=[_http_status_error(400)])

    res = write_back(store, client=client, batch_size=10, sleep=lambda s: None, max_retries=3)

    assert res["unsent"] == 1
    assert res["errors"] == 1
    # a 4xx is not retried — post_results is called exactly once
    assert len(client.calls) == 1


def test_config_error_from_headers_is_non_transient(store):
    _seed(store, "1")
    client = FakeClient(script=[RuntimeError("internal_api_key is not configured")])

    res = write_back(store, client=client, batch_size=10, sleep=lambda s: None, max_retries=3)

    assert res["unsent"] == 1
    assert len(client.calls) == 1  # RuntimeError from _headers() is not retried


# ---- batching --------------------------------------------------------------
def test_batching_chunks_and_marks_per_batch(store):
    for i in range(1, 6):  # 5 rows
        _seed(store, str(i))
    client = FakeClient()  # all-written default

    res = write_back(store, client=client, batch_size=2)

    assert [len(c) for c in client.calls] == [2, 2, 1]  # 3 batches
    assert res["batches"] == 3
    assert res["sent"] == 5
    assert store.enriched_unsent() == []


def test_no_rows_is_clean_noop(store):
    res = write_back(store, client=FakeClient(), batch_size=10)
    assert res == {"sent": 0, "batches": 0, "retries": 0, "failed": 0, "unsent": 0, "errors": 0}


# ---- E7: _cmd_write_back distinguishes unsent from no-op -------------------
def test_cmd_write_back_returns_nonzero_when_rows_unsent(store, monkeypatch):
    _seed(store, "1")
    monkeypatch.setattr(cli, "Store", lambda: store)
    import job_enricher.writeback as wb

    class FailClient:
        def post_results(self, payload):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(wb, "JVNClient", lambda: FailClient())
    rc = cli._cmd_write_back(argparse.Namespace())
    assert rc == 1


def test_cmd_write_back_returns_zero_when_nothing_to_send(store, monkeypatch):
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_write_back(argparse.Namespace())
    assert rc == 0
