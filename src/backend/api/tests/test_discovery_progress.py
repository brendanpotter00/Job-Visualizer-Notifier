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
    OUTCOME_REFUSED,
    OUTCOME_RUNNING,
    OUTCOME_TRACKING,
    STATUS_ACTIVE,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STEP_FIND_FEED,
    STEP_OPEN_PAGE,
    STEP_READY,
    STEP_VERIFY_READ,
    ProgressLedger,
    initial_snapshot,
    read_progress,
)


def _by_key(snapshot: dict) -> dict[str, dict]:
    return {step["key"]: step for step in snapshot["steps"]}


# --- the ledger ---------------------------------------------------------------

def test_a_snapshot_always_carries_all_four_steps_in_order() -> None:
    """The row carries the WHOLE checklist on every write. A poll landing mid-run must
    render four rungs, not reconstruct the missing ones."""
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
    assert all(step["status"] == STATUS_DONE for step in result["steps"])
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
