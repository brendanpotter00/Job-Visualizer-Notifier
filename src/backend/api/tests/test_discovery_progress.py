"""The 4-step discovery checklist vocabulary — pure, no DB, no network. $0.

This module is display-only: nothing here can make us scrape, close or refuse anything.
What it CAN do is 500 the one endpoint the My-Companies list depends on, or render a
harvested string into the DOM — so the properties under test are exactly those two:

* :func:`read_progress` is TOTAL. Junk, an older blob, an ATS provider config, ``None``
  — every one of them degrades to ``None`` or to a trimmed subset, never an exception.
* A preview ``url`` that is not http(s) is DROPPED on write AND on read. It is rendered
  as a link, and the value came off a stranger's job board.
* :meth:`ProgressLedger.fail` OVERRIDES a step already ticked, because a step really
  does complete and then get invalidated ("found 3 candidate feeds" → "none of them is
  a jobs list") and the ✕ has to land on the step that decided the outcome.
"""

from __future__ import annotations

from api.services.discovery.progress import (
    DISCOVERY_STEPS,
    MAX_PREVIEW_JOBS,
    MAX_REQUEST_ROWS,
    REQUEST_BLOCKED,
    REQUEST_CHOSEN,
    REQUEST_OVERSIZE,
    REQUEST_RECORDED,
    OUTCOME_REFUSED,
    OUTCOME_RUNNING,
    OUTCOME_TRACKING,
    STATUS_ACTIVE,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STEP_FIND_FEED,
    STEP_FIRST_SCAN,
    STEP_OPEN_PAGE,
    STEP_READY,
    STEP_VERIFY_READ,
    ProgressLedger,
    display_url,
    initial_snapshot,
    payload_sample,
    read_progress,
    with_first_scan,
)


def _by_key(snapshot: dict) -> dict[str, dict]:
    return {step["key"]: step for step in snapshot["steps"]}


# --- the ledger ---------------------------------------------------------------

def test_a_snapshot_always_carries_all_five_steps_in_order() -> None:
    """The row carries the WHOLE checklist on every write. A poll landing mid-run must
    render five rungs, not reconstruct the missing ones."""
    snapshot = ProgressLedger().snapshot()
    assert [step["key"] for step in snapshot["steps"]] == list(DISCOVERY_STEPS)
    assert all(step["status"] == STATUS_PENDING for step in snapshot["steps"])


def test_the_seeded_snapshot_has_step_one_already_running() -> None:
    """Written with the provisional row, before the queue picks the job up — otherwise
    the row is a bare "Setting up…" badge, i.e. the spinner this replaced."""
    steps = _by_key(initial_snapshot())
    assert steps[STEP_OPEN_PAGE]["status"] == STATUS_ACTIVE
    assert steps[STEP_FIND_FEED]["status"] == STATUS_PENDING


def test_each_finished_step_carries_its_specific_result() -> None:
    ledger = ProgressLedger()
    ledger.finish(STEP_OPEN_PAGE, "opened careers.acme.example — recorded 14 JSON request(s)")
    ledger.finish(STEP_FIND_FEED, "found 3 candidate feed(s)")
    ledger.start(STEP_VERIFY_READ)
    steps = _by_key(ledger.snapshot())

    assert steps[STEP_OPEN_PAGE]["status"] == STATUS_DONE
    assert "recorded 14" in steps[STEP_OPEN_PAGE]["result"]
    assert steps[STEP_FIND_FEED]["result"] == "found 3 candidate feed(s)"
    assert steps[STEP_VERIFY_READ]["status"] == STATUS_ACTIVE
    assert steps[STEP_READY]["status"] == STATUS_PENDING


def test_failing_a_step_overrides_a_tick_it_had_already_earned() -> None:
    """The pre-filter finds three job-shaped feeds and the selector then says none of
    them is a jobs list. Leaving the ✓ on "finding the jobs feed" would hide the only
    thing the user needs to know."""
    ledger = ProgressLedger()
    ledger.finish(STEP_FIND_FEED, "found 3 candidate feed(s)")
    ledger.fail(STEP_FIND_FEED, "none of the 14 JSON request(s) this page made is a list of job postings")
    steps = _by_key(ledger.snapshot(outcome=OUTCOME_REFUSED))

    assert steps[STEP_FIND_FEED]["status"] == STATUS_FAILED
    assert "list of job postings" in steps[STEP_FIND_FEED]["result"]


def test_an_unknown_outcome_falls_back_to_running() -> None:
    assert ProgressLedger().snapshot(outcome="banana")["outcome"] == OUTCOME_RUNNING


def test_the_job_preview_is_capped_and_reduced_to_renderable_fields() -> None:
    rows = [
        {"id": str(i), "title": f"Engineer {i}", "location": "Remote",
         "url": f"https://acme.example/jobs/{i}", "department": "Eng",
         "posted_at": "2026-01-01"}
        for i in range(MAX_PREVIEW_JOBS + 4)
    ]
    preview = ProgressLedger().snapshot(
        outcome=OUTCOME_TRACKING, job_preview=rows
    )["job_preview"]

    assert len(preview) == MAX_PREVIEW_JOBS
    # Only the three renderable fields survive — the rest of the harvested record is
    # not echoed back into a rendered page.
    assert set(preview[0]) == {"title", "location", "url"}


def test_a_preview_row_without_a_title_is_dropped() -> None:
    preview = ProgressLedger().snapshot(
        job_preview=[{"title": "", "url": "https://x.example/1"},
                     {"title": "Engineer"}]
    )["job_preview"]
    assert [row["title"] for row in preview] == ["Engineer"]


def test_a_non_http_preview_url_is_dropped_rather_than_stored() -> None:
    """The preview is RENDERED as a link and the value came off a stranger's board:
    a ``javascript:`` href stored here is stored XSS. The row survives without its
    link — an unlinked title is a fine preview entry."""
    preview = ProgressLedger().snapshot(
        job_preview=[{"title": "Engineer", "url": "javascript:alert(1)"}]
    )["job_preview"]
    assert preview == [{"title": "Engineer"}]


def test_a_non_http_live_view_url_is_dropped() -> None:
    ledger = ProgressLedger()
    ledger.set_live_view_url("javascript:alert(1)")
    assert ledger.snapshot()["live_view_url"] is None
    ledger.set_live_view_url("https://browserbase.com/devtools/x?navbar=false")
    assert ledger.snapshot()["live_view_url"].startswith("https://")


def test_a_run_with_no_browserbase_session_simply_has_no_live_view() -> None:
    """Our default is our OWN Chromium, which has no hosted view — so this is the
    normal case, not the exception (DECISION D4)."""
    assert ProgressLedger().snapshot()["live_view_url"] is None


# --- read_progress: TOTAL by contract -----------------------------------------

def test_an_ats_provider_config_yields_no_checklist() -> None:
    """A Workday/Eightfold company's provider_config shares the column. It has no
    'discovery' key, so it must read as "no checklist" — never leak into the row."""
    assert read_progress({"baseUrl": "https://wd1.myworkdayjobs.com", "tenant": "acme"}) is None


def test_junk_and_missing_input_read_as_no_checklist() -> None:
    for value in (None, {}, [], "discovery", 7, {"discovery": "yes"}, {"discovery": []}):
        assert read_progress(value) is None, value


def test_a_non_string_outcome_or_status_degrades_instead_of_raising() -> None:
    """TOTALITY, the sharp edge: ``x in frozenset`` hashes ``x``.

    A hand-edited (or older-deployment) blob holding a JSON list/object where a plain
    string belongs used to raise ``TypeError`` out of the read path, 500-ing
    ``GET /api/users/companies`` over a display-only field.
    """
    result = read_progress({
        "discovery": {
            "outcome": ["running"],
            "steps": [
                {"key": STEP_OPEN_PAGE, "status": {"done": True}},
                {"key": STEP_FIND_FEED, "status": ["active"]},
            ],
        }
    })
    assert result is not None
    assert result["outcome"] == OUTCOME_RUNNING
    steps = _by_key(result)
    assert steps[STEP_OPEN_PAGE]["status"] == STATUS_PENDING
    assert steps[STEP_FIND_FEED]["status"] == STATUS_PENDING


def test_a_blob_from_an_older_deployment_is_trimmed_not_raised_on() -> None:
    """Unknown step keys are dropped and missing ones filled as pending, so the
    frontend's closed step union always receives exactly the four it maps."""
    result = read_progress({
        "discovery": {
            "steps": [
                {"key": "open_page", "status": "done", "result": "opened x"},
                {"key": "some_future_step", "status": "done", "result": "?"},
                {"key": "find_feed", "status": "not_a_status"},
                "not even a dict",
            ],
            "outcome": "who_knows",
            "job_preview": "not a list",
        }
    })
    assert result is not None
    assert [step["key"] for step in result["steps"]] == list(DISCOVERY_STEPS)
    steps = _by_key(result)
    assert steps[STEP_OPEN_PAGE]["status"] == STATUS_DONE
    # An unrecognised status is a pending step, never a rendered raw code.
    assert steps[STEP_FIND_FEED]["status"] == STATUS_PENDING
    assert steps[STEP_READY]["status"] == STATUS_PENDING
    assert result["outcome"] == OUTCOME_RUNNING
    assert result["job_preview"] == []


def test_read_back_preserves_a_real_terminal_blob() -> None:
    ledger = ProgressLedger()
    ledger.finish(STEP_OPEN_PAGE, "opened careers.acme.example — recorded 9 JSON request(s)")
    ledger.finish(STEP_FIND_FEED, "found 2 candidate feed(s)")
    ledger.finish(STEP_VERIFY_READ, "read 90 job(s)")
    ledger.finish(STEP_READY, "reading the board's own feed directly — no browser needed")
    stored = {"discovery": ledger.snapshot(
        outcome=OUTCOME_TRACKING,
        job_preview=[{"title": "Staff Engineer", "location": "Remote",
                      "url": "https://acme.example/jobs/1"}],
    )}

    result = read_progress(stored)
    assert result is not None
    assert result["outcome"] == OUTCOME_TRACKING
    assert all(
        _by_key(result)[key]["status"] == STATUS_DONE
        for key in (STEP_OPEN_PAGE, STEP_FIND_FEED, STEP_VERIFY_READ, STEP_READY)
    )
    # The FIFTH rung belongs to the harvest, not to discovery: a terminal discovery blob
    # must NOT tick it, or the checklist is green again over a company with no jobs.
    assert _by_key(result)[STEP_FIRST_SCAN]["status"] == STATUS_PENDING
    assert _by_key(result)[STEP_VERIFY_READ]["result"] == "read 90 job(s)"
    assert result["job_preview"] == [
        {"title": "Staff Engineer", "location": "Remote",
         "url": "https://acme.example/jobs/1"}
    ]


def test_read_back_drops_an_unsafe_preview_url_written_before_the_check_existed() -> None:
    """Validate on WRITE and again on READ: a blob already in the database predates
    whatever we tighten later, and this one is rendered."""
    result = read_progress({
        "discovery": {
            "steps": [],
            "outcome": OUTCOME_TRACKING,
            "job_preview": [{"title": "Engineer", "url": "javascript:alert(1)"}],
            "live_view_url": "data:text/html,<script>alert(1)</script>",
        }
    })
    assert result is not None
    assert result["job_preview"] == [{"title": "Engineer"}]
    assert result["live_view_url"] is None


# --- with_first_scan: the harvest's one write into discovery's blob ------------


def _terminal_blob() -> dict:
    ledger = ProgressLedger()
    ledger.finish(STEP_OPEN_PAGE, "opened acme.example — recorded 9 JSON request(s)")
    ledger.finish(STEP_FIND_FEED, "found 2 candidate feed(s)")
    ledger.finish(STEP_VERIFY_READ, "read 90 job(s)")
    ledger.finish(STEP_READY, "reading the board's own feed directly")
    ledger.start(STEP_FIRST_SCAN)
    return {"discovery": ledger.snapshot(outcome=OUTCOME_TRACKING)}


def test_a_landed_first_scan_ticks_only_its_own_rung() -> None:
    """The harvest owns exactly ONE rung. Touching any other would let a nightly run
    rewrite what discovery found — the two are different runs, days apart."""
    result = with_first_scan(_terminal_blob(), ok=True, detail="read 88 job(s) from the board")
    assert result is not None
    steps = _by_key(result)
    assert steps[STEP_FIRST_SCAN]["status"] == STATUS_DONE
    assert steps[STEP_FIRST_SCAN]["result"] == "read 88 job(s) from the board"
    assert steps[STEP_VERIFY_READ]["result"] == "read 90 job(s)"
    assert steps[STEP_OPEN_PAGE]["status"] == STATUS_DONE


def test_a_failed_first_scan_marks_the_rung_without_refusing_the_board() -> None:
    """A first scan that fails is not a refusal: the board is still readable (discovery
    proved that), so the run-level outcome must stay 'tracking' and only the rung go ✕."""
    result = with_first_scan(_terminal_blob(), ok=False, detail="the board timed out")
    assert result is not None
    assert result["outcome"] == OUTCOME_TRACKING
    assert _by_key(result)[STEP_FIRST_SCAN]["status"] == STATUS_FAILED
    assert _by_key(result)[STEP_FIRST_SCAN]["result"] == "the board timed out"


def test_a_success_overwrites_an_earlier_failed_rung() -> None:
    """Deliberately not "only if still pending". Tonight's success has to be able to
    clear last night's ✕, or the row carries an error that is no longer true."""
    failed = {"discovery": with_first_scan(_terminal_blob(), ok=False, detail="nope")}
    healed = with_first_scan(failed, ok=True, detail="read 12 job(s) from the board")
    assert healed is not None
    assert _by_key(healed)[STEP_FIRST_SCAN]["status"] == STATUS_DONE


def test_a_row_written_before_the_rung_existed_still_gets_one() -> None:
    """A board discovered before this rung shipped has a four-step blob. ``read_progress``
    fills the fifth as pending, so its next nightly harvest self-heals it to a ✓ — no
    backfill migration for a display-only field."""
    legacy = {"discovery": {"steps": [
        {"key": STEP_OPEN_PAGE, "status": STATUS_DONE, "result": "opened acme.example"},
        {"key": STEP_FIND_FEED, "status": STATUS_DONE, "result": "found 1 candidate feed(s)"},
        {"key": STEP_VERIFY_READ, "status": STATUS_DONE, "result": "read 4 job(s)"},
        {"key": STEP_READY, "status": STATUS_DONE, "result": "reading the board"},
    ], "outcome": OUTCOME_TRACKING}}
    result = with_first_scan(legacy, ok=True, detail="read 4 job(s) from the board")
    assert result is not None
    assert _by_key(result)[STEP_FIRST_SCAN]["status"] == STATUS_DONE


def test_a_config_with_no_checklist_writes_nothing() -> None:
    """None means "this row has no checklist" — every ATS company. The caller must then
    write NOTHING, which is what keeps a display-only blob off the harvest's path and
    off provider_configs that mean something else entirely."""
    assert with_first_scan({}, ok=True, detail="read 4 job(s)") is None
    assert with_first_scan(None, ok=True, detail="read 4 job(s)") is None
    assert with_first_scan(
        {"workday_host": "acme.wd1.myworkdayjobs.com"}, ok=True, detail="read 4 job(s)"
    ) is None


def test_a_pathological_detail_cannot_bloat_every_row_of_the_list() -> None:
    """The detail comes from an exception string and is RENDERED. Clipped on write for
    the same reason every other result string is."""
    result = with_first_scan(_terminal_blob(), ok=False, detail="x" * 5000)
    assert result is not None
    assert len(_by_key(result)[STEP_FIRST_SCAN]["result"]) <= 400


# --------------------------------------------------------------------------
# THE NETWORK LOG — the evidence panel, and the secrets it must never carry
# --------------------------------------------------------------------------

def test_a_url_is_published_without_its_credentials_or_query_values() -> None:
    """THE secret-safety test. Every one of these is a real thing a board does.

    Userinfo is a credential written into a URL; a port is noise; and a query VALUE is
    where a board that signs its URLs puts the signature — so values go and names stay,
    because there is no way to tell a signed parameter from a benign one by name.
    """
    published = display_url(
        "https://user:hunter2@jobs.example.com:8443/api/search?limit=20&sig=deadbeef"
    )
    assert published == "https://jobs.example.com/api/search?limit=…&sig=…"
    assert "hunter2" not in published
    assert "deadbeef" not in published
    assert "8443" not in published


def test_an_opaque_token_in_query_position_is_not_republished_as_a_name() -> None:
    """The subtle half. ``parse_qsl(keep_blank_values=True)`` hands a bare signature back
    as a parameter NAME, which would publish verbatim the exact thing the rule above
    exists to suppress. A segment with no ``=`` is not a parameter."""
    published = display_url("https://jobs.example.com/api?eyJhbGciOiJIUzI1NiJ9deadbeef")
    assert published == "https://jobs.example.com/api?…"
    assert "eyJhbGci" not in published


def test_an_absurd_parameter_name_is_dropped_rather_than_echoed() -> None:
    """Same reasoning one step further: a 300-character "name" is a payload, not a
    schema, and it is also how one row of a polled list response gets fat."""
    published = display_url("https://jobs.example.com/api?" + "s" * 300 + "=1")
    assert published == "https://jobs.example.com/api?…"


def test_display_url_never_raises_on_junk() -> None:
    """It runs inside the writer AND inside ``read_progress``, whose whole contract is
    that nothing raises."""
    assert display_url(None) == "(unreadable URL)"
    assert display_url(12) == "(unreadable URL)"
    assert display_url("   ") == "(unreadable URL)"


def test_a_payload_sample_redacts_credential_keys_and_clips_long_strings() -> None:
    """A board can echo its own session token back inside the JSON it serves, and a
    single job description can be tens of kilobytes of HTML. Both are rendered."""
    sample = payload_sample({
        "title": "Staff Engineer",
        "sessionToken": "s3cr3t-value",
        "description": "x" * 5000,
    })
    assert sample is not None
    assert "s3cr3t-value" not in sample
    assert "Staff Engineer" in sample
    # The budget is spent on SHAPE — every key visible — not on one giant string.
    assert len(sample) < 1500


def test_a_recorded_request_says_nothing_about_its_contents_until_it_is_scored() -> None:
    """``records: null`` and ``records: 0`` mean opposite things: "we have not looked"
    versus "we looked and there were no jobs in it". The second is the whole evidence
    for the commonest refusal we serve, so they cannot collapse."""
    ledger = ProgressLedger()
    ledger.note_request(
        method="get", url="https://b.example/api/jobs", status=200, size_bytes=4096
    )
    assert ledger.snapshot()["network"]["requests"][0]["records"] is None
    ledger.score_requests({})
    assert ledger.snapshot()["network"]["requests"][0]["records"] == 0


def test_the_chosen_request_carries_the_sample_and_the_reason_it_won() -> None:
    ledger = ProgressLedger()
    ledger.note_request(method="GET", url="https://b.example/ping", status=204, size_bytes=12)
    ledger.note_request(method="POST", url="https://b.example/api/jobs", status=200, size_bytes=90_000)
    ledger.score_requests({1: 88})
    ledger.choose_request(
        1, note="88 job(s) came back", records_path="data.jobs", records=88,
        sample='{"title": "Engineer"}',
    )
    network = ledger.snapshot()["network"]
    assert [row["state"] for row in network["requests"]] == [
        REQUEST_RECORDED, REQUEST_CHOSEN
    ]
    assert network["requests"][1]["note"] == "88 job(s) came back"
    assert network["sample"] == {
        "path": "data.jobs", "records": 88, "text": '{"title": "Engineer"}'
    }


def test_an_oversize_body_keeps_its_size_and_is_never_scored_as_empty() -> None:
    """OUR ceiling, not the board's. Scoring it 0 would report the one response that
    almost certainly WAS the jobs feed as containing no jobs."""
    ledger = ProgressLedger()
    ledger.note_request(
        method="GET", url="https://b.example/api/jobs", status=200,
        size_bytes=2_775_685, truncated=True,
    )
    ledger.score_requests({})
    row = ledger.snapshot()["network"]["requests"][0]
    assert row["state"] == REQUEST_OVERSIZE
    assert row["records"] is None
    assert row["bytes"] == 2_775_685


def test_a_job_shaped_request_at_a_refused_address_says_so() -> None:
    ledger = ProgressLedger()
    ledger.note_request(method="GET", url="http://10.0.0.1/api/jobs", status=200, size_bytes=900)
    ledger.score_requests({0: 4}, blocked=[0])
    row = ledger.snapshot()["network"]["requests"][0]
    assert row["state"] == REQUEST_BLOCKED
    assert row["note"] == "we refuse to fetch this address"


def test_the_log_cannot_grow_past_the_captures_own_ceiling() -> None:
    """The capture records at most 40 responses, so publishing more than 40 rows would
    be publishing something that did not happen."""
    ledger = ProgressLedger()
    for i in range(80):
        ledger.note_request(
            method="GET", url=f"https://b.example/x{i}", status=200, size_bytes=10
        )
    assert len(ledger.snapshot()["network"]["requests"]) == MAX_REQUEST_ROWS


def test_the_whole_blob_stays_small_enough_to_poll_every_four_seconds() -> None:
    """The per-row caps MULTIPLY; the aggregate one does not, and it is the number that
    actually bounds what every open tab re-downloads while a discovery runs.

    The pathological board here — forty responses with 160-character URLs — is what the
    aggregate cap exists for, so this asserts BOTH halves of the degradation: rows are
    dropped, and the count above them keeps telling the truth about what we saw.
    """
    import json as _json

    ledger = ProgressLedger()
    for i in range(MAX_REQUEST_ROWS):
        ledger.note_request(
            method="OPTIONS",
            url=f"https://board.example.com/{'p' * 120}/{i}?a=1&b=2&c=3&d=4",
            status=200,
            size_bytes=4_000_000,
        )
    ledger.score_requests({i: 9999 for i in range(MAX_REQUEST_ROWS)})
    ledger.choose_request(
        0, note="x" * 400, records_path="y" * 200, records=9999, sample="z" * 4000
    )
    snapshot = ledger.snapshot()
    assert len(snapshot["network"]["requests"]) < MAX_REQUEST_ROWS
    assert snapshot["network"]["recorded"] == MAX_REQUEST_ROWS
    blob = _json.dumps(snapshot)
    assert len(blob) < 11_000, len(blob)


def test_a_hostile_network_blob_is_trimmed_rather_than_raised_on() -> None:
    """``read_progress`` is the one reader that must never raise — its caller is the
    endpoint the My-Companies list cannot live without."""
    read = read_progress({"discovery": {"network": {
        "requests": [
            "not a row",
            {"method": ["GET"], "url": None, "status": True, "bytes": "big",
             "records": "many", "state": {"nope": 1}, "note": 7},
            {"url": "https://b.example/a?k=v", "status": 200, "bytes": 10,
             "records": 3, "state": REQUEST_CHOSEN},
        ],
        "recorded": "twelve",
        "sample": {"path": None, "records": None, "text": ""},
    }}})
    assert read is not None
    rows = read["network"]["requests"]
    assert len(rows) == 2
    assert rows[0] == {
        "method": "GET", "url": "(unreadable URL)", "status": 0, "bytes": 0,
        "records": None, "state": REQUEST_RECORDED, "note": None,
    }
    assert rows[1]["url"] == "https://b.example/a?k=…"
    assert rows[1]["state"] == REQUEST_CHOSEN
    # A counter hand-edited below the rows it heads would render "0 requests" over two.
    assert read["network"]["recorded"] == 2
    # A sample with no text is not a sample.
    assert read["network"]["sample"] is None


def test_a_blob_written_before_the_network_log_existed_reads_as_an_empty_one() -> None:
    """Same self-healing rule as the fifth rung: an older row renders the panel it
    always rendered, with no evidence section and no crash."""
    read = read_progress({"discovery": {"steps": [], "outcome": OUTCOME_TRACKING}})
    assert read is not None
    assert read["network"] == {"requests": [], "recorded": 0, "sample": None}


def test_the_url_is_redacted_again_on_the_way_out() -> None:
    """A blob already in the database predates whatever we tighten later, so the
    redaction that matters is the one that runs on READ."""
    read = read_progress({"discovery": {"network": {"requests": [
        {"method": "GET", "url": "https://user:pw@b.example:9/api?sig=leaked",
         "status": 200, "bytes": 1, "records": 0, "state": REQUEST_RECORDED},
    ]}}})
    assert read is not None
    assert read["network"]["requests"][0]["url"] == "https://b.example/api?sig=…"


def test_first_scan_does_not_lose_the_evidence_the_run_collected() -> None:
    """``with_first_scan`` round-trips the blob through ``read_progress``; the network
    log has to survive that or a tracked board's receipt loses its evidence."""
    ledger = ProgressLedger()
    ledger.note_request(method="GET", url="https://b.example/api/jobs", status=200, size_bytes=90)
    ledger.score_requests({0: 12})
    ledger.choose_request(0, note="12 job(s) came back", records=12, sample="{}")
    updated = with_first_scan(
        {"discovery": ledger.snapshot(outcome=OUTCOME_TRACKING)}, ok=True, detail="12 jobs"
    )
    assert updated is not None
    assert updated["network"]["requests"][0]["state"] == REQUEST_CHOSEN
    assert updated["network"]["sample"]["text"] == "{}"
