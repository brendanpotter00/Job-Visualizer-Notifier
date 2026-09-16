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
import os

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


# ---- ENR-WB-1: subcategories behind a knob, with NULL preserved --------------
#
# ⚠ WHY A KNOB, AND WHY THE ACCEPTANCE IS A READ-BACK.
# JVN's `EnrichmentResultItem` (models.py:879, model_config at :906) sets
# `alias_generator=to_camel, populate_by_name=True` and NOTHING else — no
# `extra='forbid'`. Pydantic's default is `ignore`, so an EARLY `subcategories`
# field is SILENTLY DROPPED and the row still counts as `written`. The failure is
# not a 422 you would notice; it is a clean-looking success that persists nothing.
# Every assertion below is therefore on the PARSED REQUEST BODY or on a READ-BACK
# — never on `written: N`.

from job_enricher import enrich_config as ec  # noqa: E402


def _set_subcats(store, jid, value, source="classify", conf=None, source_id="greenhouse"):
    with store.connect() as c:
        c.execute(
            "UPDATE enrichments SET subcategories=?, subcategory_source=?, "
            "subcategory_confidence=? WHERE source_id=? AND job_listing_id=?",
            (value, source, conf, source_id, jid),
        )


def test_payload_OMITS_both_keys_when_the_knob_is_off(store):
    _seed(store, "1")
    _set_subcats(store, "1", '["backend"]', conf=0.8)
    client = FakeClient()
    write_back(store, client=client)
    item = client.calls[0][0]
    assert "subcategories" not in item
    assert "subcategory_confidence" not in item
    assert "subcategory_source" not in item


def test_payload_includes_both_keys_when_the_knob_is_on(store):
    _seed(store, "1")
    _set_subcats(store, "1", '["backend"]', conf=0.8)
    ec.set_writeback_send_subcategories(store, True)
    client = FakeClient()
    write_back(store, client=client)
    item = client.calls[0][0]
    assert item["subcategories"] == ["backend"]
    assert item["subcategory_confidence"] == 0.8
    assert item["subcategory_source"] == "classify"


def test_subcategory_source_ships_on_every_row_whose_array_is_a_list(store):
    """⚠ SHARED CONTRACT 1.2 A, THE THIRD KEY. `subcategory_source` MUST be
    present whenever the array is a list — INCLUDING `[]` — and null when the
    array is null.

    Without it JVN's `enrichment_subcategory_source` stays NULL for every
    live-lane row, which silently disables BOTH things that column exists for:
    the per-field human lock (`= 'human'`, the only reason a backfill does not
    stomp a human correction) and a rollback scoped to one lane instead of
    nuclear. It fails as a clean 200, so nothing downstream notices.
    ASSERTED ON THE PARSED REQUEST BODY, never on `written: N`."""
    _seed(store, "1")   # subcategories stays NULL -> source must be null
    _seed(store, "2")
    _set_subcats(store, "2", "[]", source="classify")       # evaluated, none apply
    _seed(store, "3")
    _set_subcats(store, "3", '["backend"]', source="judge")  # a judge label
    ec.set_writeback_send_subcategories(store, True)
    client = FakeClient()
    write_back(store, client=client)
    items = {i["job_listing_id"]: i for i in client.calls[0]}

    assert items["1"]["subcategories"] is None
    assert items["1"]["subcategory_source"] is None
    # `[]` is a LIST: it carries a source, or the row's provenance is lost even
    # though it left the backfill queue.
    assert items["2"]["subcategories"] == []
    assert items["2"]["subcategory_source"] == "classify"
    assert items["3"]["subcategory_source"] == "judge"
    for item in items.values():
        assert "subcategory_source" in item


def test_a_labelled_row_with_no_source_is_logged_not_shipped_silently(store, caplog):
    """The one shape the contract cannot express. Post-fix every writer stamps a
    source alongside the array, so this is unreachable — but if it ever happens
    it must be VISIBLE rather than a clean 200 with a null provenance."""
    import logging

    _seed(store, "1")
    _set_subcats(store, "1", '["backend"]', source=None, conf=0.8)
    ec.set_writeback_send_subcategories(store, True)
    client = FakeClient()
    with caplog.at_level(logging.WARNING, logger="job_enricher.writeback"):
        write_back(store, client=client)
    assert "NO subcategory_source" in caplog.text
    assert client.calls[0][0]["subcategory_source"] is None


def test_the_three_column_states_map_to_null_empty_and_a_list(store):
    """⚠ ASSERTED ON THE PARSED REQUEST BODY, and specifically that NULL is
    NEITHER the string '[]' NOR []. Collapsing NULL into [] would tell JVN every
    unevaluated row is 'evaluated, none apply' and drain the backfill queue."""
    _seed(store, "1")   # subcategories stays NULL
    _seed(store, "2")
    _set_subcats(store, "2", "[]")
    _seed(store, "3")
    _set_subcats(store, "3", '["backend"]')
    ec.set_writeback_send_subcategories(store, True)
    client = FakeClient()
    write_back(store, client=client)
    by_id = {i["job_listing_id"]: i for i in client.calls[0]}

    assert by_id["1"]["subcategories"] is None
    assert by_id["1"]["subcategories"] != []
    assert by_id["1"]["subcategories"] != "[]"
    assert by_id["2"]["subcategories"] == []
    assert by_id["3"]["subcategories"] == ["backend"]


def _round_trip_helper(written_response, read_back_payload, expected):
    """THE ASSERTION SHAPE, factored out so it can be pinned.

    Takes what JVN CLAIMED (`{"written": N}`) and what a subsequent READ actually
    returns. It ignores the claim entirely — a silent Pydantic drop inflates
    exactly that count, which is the whole reason this exists."""
    assert written_response.get("written", 0) >= 0      # deliberately not evidence
    return (read_back_payload or {}).get("subcategories") == expected


def test_written_count_alone_is_not_evidence():
    """⚠ PINS THE ASSERTION SHAPE so nobody 'simplifies' the round trip into a
    count check. JVN says `written: 1` for a request that carried the field, and
    the read-back comes back WITHOUT it — that must FAIL."""
    assert _round_trip_helper({"written": 1}, {"category": "software_engineering"},
                              ["backend"]) is False
    assert _round_trip_helper({"written": 1}, {"subcategories": ["backend"]},
                              ["backend"]) is True


@pytest.mark.network
@pytest.mark.skipif(
    not os.environ.get("JVN_BASE_URL_SCHEMA4"),
    reason=(
        "the certified round trip needs a LOCAL JVN that has shipped SCHEMA-4 "
        "(EnrichmentResultItem.subcategories + the enrichment_writer column "
        "write). Set JVN_BASE_URL_SCHEMA4 to run it."
    ),
)
def test_subcategory_round_trip_read_back(store):
    """THE CERTIFIED ROUND TRIP, enricher side.

    ⚠ ASSERT ON THE READ, NEVER ON `written: N`. JVN's EnrichmentResultItem has
    no `extra='forbid'`, so before SCHEMA-4 an unknown `subcategories` key is
    SILENTLY DROPPED while the row still counts as written — a clean-looking
    success that persists nothing.
    """
    import httpx

    base = os.environ["JVN_BASE_URL_SCHEMA4"].rstrip("/")
    _seed(store, "1")
    _set_subcats(store, "1", '["backend"]', conf=0.8)
    ec.set_writeback_send_subcategories(store, True)
    result = write_back(store)
    read_back = httpx.get(f"{base}/api/jobs/greenhouse/1", timeout=30.0).json()
    assert _round_trip_helper(result, read_back, ["backend"])


def test_jvn_warnings_about_a_soft_nulled_subcategory_are_logged(store, caplog):
    _seed(store, "1")
    _set_subcats(store, "1", '["backend"]')
    ec.set_writeback_send_subcategories(store, True)
    client = FakeClient([{
        "written": 1, "failed": [],
        "warnings": [{"source_id": "greenhouse", "job_listing_id": "1",
                      "warnings": ["subcategory 'ai_ml' not in enum; soft-nulled"]}],
    }])
    with caplog.at_level(logging.WARNING):
        write_back(store, client=client)
    assert "soft-nulled" in caplog.text


def test_the_writeback_knob_defaults_FALSE_and_rides_config_snapshot(store):
    """⚠ SHIPS DARK. It may only be flipped ON after JVN has SCHEMA-4."""
    assert ec.get_writeback_send_subcategories(store) is False
    assert ec.config_snapshot(store)["writeback_send_subcategories"] is False
    ec.set_writeback_send_subcategories(store, True)
    assert ec.get_writeback_send_subcategories(store) is True


def test_a_confidence_without_a_label_never_reaches_the_wire(store):
    """⚠ SHARED CONTRACT 1.2 A at the wire boundary. A row whose subcategories are
    NULL or `[]` must ship `subcategory_confidence: null` whatever the column
    holds — otherwise JVN calibrates confidence over unlabelled rows, and the
    write still looks like a clean `written: N`. ASSERTED ON THE PARSED REQUEST
    BODY, never on the count."""
    _seed(store, "1")
    _seed(store, "2")
    _set_subcats(store, "1", None, source=None, conf=0.7)     # never evaluated
    _set_subcats(store, "2", "[]", conf=0.7)                  # none apply
    ec.set_writeback_send_subcategories(store, True)
    client = FakeClient()
    write_back(store, client=client)
    items = {i["job_listing_id"]: i for i in client.calls[0]}
    assert items["1"]["subcategories"] is None
    assert items["1"]["subcategory_confidence"] is None
    assert items["2"]["subcategories"] == []
    assert items["2"]["subcategory_confidence"] is None
