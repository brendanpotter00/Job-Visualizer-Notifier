"""U6 — the recipe path learns to produce a date (POSTED-DATE-PLAN.md §5/U6).

``parse_date`` has been fully implemented in the runner since Phase 3a and was
**never emitted**: ``synthesize_recipe`` wrote ``fetch`` / ``paginate_*`` /
``extract_json_path`` / ``assert_no_inband_error`` / ``dedupe_key`` / ``assert_unique``
and nothing else, so 0 of 7 stored recipes carried one. The measured cost of that on
the local dev DB: **2,217 of 2,217** rows on the discovered Microsoft board stored a
NULL ``posted_on`` while every record in the payload carried
``postedTs: 1787617881`` — a unix epoch that ``datetime.fromisoformat`` can only
raise on.

This module is the first behavioural coverage ``_parse_date_value`` and
``_apply_shaping`` have ever had, so it pins the modes that already existed as well as
the two U6 adds. Three properties are load-bearing and each has its own test rather
than riding along in an assertion:

* **never ``now()``** — a board that publishes no date, or one we cannot read, stores
  NULL. Synthesising "today" is what bakes a day-one spike into the trend graph.
* **RAISES-never-empty** — date handling degrades a FIELD. A payload where every
  single date fails to parse still returns every row.
* **never-wrong-close** — nothing here may raise, because this code runs in the same
  task as the close sweep.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.services.capture import request_selector as rs
from api.services.capture.discover import synthesize_recipe
from api.services.capture.request_selector import (
    PaginationHint,
    PostedDateFormat,
    RequestSelection,
    detect_posted_at_format,
    prefilter_candidates,
)
from api.services.recipe_runner import (
    RecipeExecutionError,
    _apply_shaping,
    _parse_date_value,
    run_recipe,
)
from api.services.recipe_schema import PARSE_DATE_MODES, RecipeError, validate_recipe
from api.tests.test_capture_discover import (
    _AMAZON_MAP,
    _AMAZON_URL,
    _amazon_response,
    _amazon_body,
)
from api.tests.test_request_selector import _AMAZON_ANSWER, _answering, _capture

# The real value recorded off apply.careers.microsoft.com — unix SECONDS. Its
# millisecond twin is the same instant ×1000. Both must land in 2026: read the
# seconds as milliseconds and you get January 1970, read the milliseconds as
# seconds and you get the year 58,600. Those are the two silent failures the
# magnitude guard exists to stop, and they are silent precisely because neither
# raises.
_MS_EPOCH_S = 1787617881
_MS_EPOCH_MS = 1787617881000


def _step(mode: str, fmt: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"op": "parse_date", "field": "posted_at", "mode": mode}
    if fmt is not None:
        step["format"] = fmt
    return step


# --------------------------------------------------------------------------
# _parse_date_value — the modes that already existed
# --------------------------------------------------------------------------

def test_iso_mode_passes_the_boards_own_string_through_stripped() -> None:
    assert _parse_date_value("  2026-08-26T04:00:00Z  ", _step("iso")) == (
        "2026-08-26T04:00:00Z"
    )


def test_strptime_mode_reads_amazons_real_double_spaced_date() -> None:
    """amazon.jobs really does publish ``'August  9, 2026'`` with two spaces.

    Note the ``_MULTISPACE_RE`` collapse in this function is NOT what makes this pass —
    ``strptime`` already matches a space in the pattern against arbitrary whitespace,
    so removing the collapse changes nothing here (verified: an equivalent mutant). The
    behaviour is what is pinned; the mechanism is incidental."""
    assert _parse_date_value("August  9, 2026", _step("strptime", "%B %d, %Y")) == (
        "2026-08-09"
    )


def test_strptime_mode_returns_none_when_the_board_changes_its_spelling() -> None:
    """A format that stops fitting writes NULL, not a guess and not an exception."""
    assert _parse_date_value("09/08/2026", _step("strptime", "%B %d, %Y")) is None


def test_humanized_mode_is_none_by_design_not_by_omission() -> None:
    """POSTED-DATE-PLAN.md §3: a board that gives us a bucket has given us no date.
    This was once filed as a bug ("a declared no-op"); under the plan's rule it is the
    correct answer, and turning "about 12 hours" into a timestamp would be exactly the
    fabrication Workday's ``30+ Days Ago`` branch is being fixed for."""
    assert _parse_date_value("about 12 hours", _step("humanized")) is None
    assert _parse_date_value("3 days ago", _step("humanized")) is None


@pytest.mark.parametrize("value", [None, "", "   ", [], {}, 12.5])
def test_a_non_string_never_reaches_the_string_modes(value: Any) -> None:
    assert _parse_date_value(value, _step("iso")) is None
    assert _parse_date_value(value, _step("strptime", "%B %d, %Y")) is None


# --------------------------------------------------------------------------
# _parse_date_value — the epoch modes U6 adds
# --------------------------------------------------------------------------

def test_epoch_seconds_land_in_2026_not_1970() -> None:
    parsed = _parse_date_value(_MS_EPOCH_S, _step("epoch_s"))
    assert parsed is not None and parsed.startswith("2026-")


def test_epoch_milliseconds_land_in_2026_not_year_58000() -> None:
    parsed = _parse_date_value(_MS_EPOCH_MS, _step("epoch_ms"))
    assert parsed is not None and parsed.startswith("2026-")


@pytest.mark.parametrize("mode", ["epoch_s", "epoch_ms"])
@pytest.mark.parametrize("value", [_MS_EPOCH_S, _MS_EPOCH_MS])
def test_either_magnitude_under_either_mode_still_lands_in_2026(
    mode: str, value: int
) -> None:
    """The mode records what discovery SAMPLED; the magnitude decides what is parsed.
    A board that switches between seconds and milliseconds after capture would
    otherwise write 1970 or 58,600 into the column the product sorts by — every night,
    with no error anywhere."""
    parsed = _parse_date_value(value, _step(mode))
    assert parsed is not None and parsed.startswith("2026-")


def test_an_epoch_arriving_as_a_numeric_string_is_still_an_epoch() -> None:
    assert _parse_date_value(str(_MS_EPOCH_S), _step("epoch_s")) == (
        _parse_date_value(_MS_EPOCH_S, _step("epoch_s"))
    )


@pytest.mark.parametrize(
    "value", [None, "", "not-a-number", "2026-08-26", 0, -1, True, False, [], {}]
)
def test_an_unreadable_epoch_writes_null_and_never_raises(value: Any) -> None:
    """``True`` is in here on purpose: it is an ``int``, and epoch 1 is 1970-01-01.
    A boolean that leaked into a date field is not a date."""
    assert _parse_date_value(value, _step("epoch_s")) is None
    assert _parse_date_value(value, _step("epoch_ms")) is None


def test_an_epoch_outside_datetimes_range_writes_null_rather_than_exploding() -> None:
    assert _parse_date_value(10**30, _step("epoch_s")) is None
    assert _parse_date_value(float("inf"), _step("epoch_s")) is None
    assert _parse_date_value(float("nan"), _step("epoch_s")) is None


# --------------------------------------------------------------------------
# _apply_shaping — a bad date degrades a FIELD, never a row and never the run
# --------------------------------------------------------------------------

def test_shaping_touches_only_the_named_field() -> None:
    rows = [{"id": "1", "title": "SWE", "posted_at": _MS_EPOCH_S}]
    shaped = _apply_shaping(rows, [_step("epoch_s")])
    assert shaped[0]["id"] == "1" and shaped[0]["title"] == "SWE"
    assert str(shaped[0]["posted_at"]).startswith("2026-")


def test_every_row_survives_when_every_single_date_fails_to_parse() -> None:
    """RAISES-never-empty, at the shaping seam. Dropping the unparseable rows here
    would turn a board with bad dates into a smaller harvest — and a smaller harvest
    is what the completeness gate reads as jobs having disappeared."""
    rows = [{"id": str(i), "title": "SWE", "posted_at": "who knows"} for i in range(50)]
    shaped = _apply_shaping(rows, [_step("epoch_s")])
    assert len(shaped) == 50
    assert all(r["posted_at"] is None for r in shaped)
    assert all(r["id"] for r in shaped)


# --------------------------------------------------------------------------
# detect_posted_at_format — what the captured bytes actually say
# --------------------------------------------------------------------------

def test_microsoft_shaped_records_are_detected_as_epoch_seconds() -> None:
    records = [{"postedTs": _MS_EPOCH_S + i} for i in range(10)]
    assert detect_posted_at_format(records, "postedTs") == PostedDateFormat("epoch_s")


def test_millisecond_records_are_detected_as_epoch_milliseconds() -> None:
    records = [{"t": _MS_EPOCH_MS + i} for i in range(10)]
    assert detect_posted_at_format(records, "t") == PostedDateFormat("epoch_ms")


def test_an_iso_board_is_detected_as_iso_so_no_step_is_emitted() -> None:
    records = [{"p": "2026-08-26T04:00:00Z"}, {"p": "2026-08-25"}]
    assert detect_posted_at_format(records, "p") == PostedDateFormat("iso")


def test_the_real_amazon_capture_is_detected_as_its_strptime_format() -> None:
    """Straight off the recorded fixture, double space and all."""
    records = _amazon_body()["jobs"]
    assert detect_posted_at_format(records, "posted_date") == PostedDateFormat(
        "strptime", "%B %d, %Y"
    )


def test_a_humanized_board_is_no_format_at_all() -> None:
    records = [{"p": "about 12 hours"}, {"p": "3 days ago"}]
    assert detect_posted_at_format(records, "p") is None


def test_an_id_shaped_integer_is_not_mistaken_for_a_timestamp() -> None:
    """Microsoft's ``atsJobId: 200050821`` is a large int in a jobs payload and reads
    as 1976 if you call it unix time. The plausibility window is what separates a
    timestamp from an identifier."""
    records = [{"atsJobId": 200050821 + i} for i in range(5)]
    assert detect_posted_at_format(records, "atsJobId") is None


def test_an_ambiguous_all_numeric_date_is_refused_rather_than_guessed() -> None:
    """``03/07/2026`` is March 7th or July 3rd depending on the board's country, and
    nothing in the payload says which. A NULL is visibly a fallback; a confidently
    wrong date in the sort key is not."""
    records = [{"p": "03/07/2026"}, {"p": "04/08/2026"}]
    assert detect_posted_at_format(records, "p") is None


def test_a_format_that_fits_only_some_rows_is_not_this_boards_format() -> None:
    records = [{"p": "August 9, 2026"}, {"p": "August 9, 2026"}, {"p": "yesterday"}]
    assert detect_posted_at_format(records, "p") is None


def test_a_board_that_publishes_nothing_in_the_field_has_no_format() -> None:
    assert detect_posted_at_format([{"p": None}, {"p": ""}], "p") is None
    assert detect_posted_at_format([], "p") is None


def test_a_field_that_is_an_epoch_on_only_some_rows_is_not_an_epoch_field() -> None:
    """A placeholder mixed in with real timestamps means the field is not reliably a
    date. Reading the epoch rows and NULLing the rest sounds harmless until you notice
    it is the same evidence that would justify reading a field that is only
    coincidentally numeric."""
    assert detect_posted_at_format([{"p": _MS_EPOCH_S}, {"p": "n/a"}], "p") is None


def test_a_field_that_mixes_seconds_and_milliseconds_has_no_single_format() -> None:
    assert detect_posted_at_format(
        [{"p": _MS_EPOCH_S}, {"p": _MS_EPOCH_MS}], "p"
    ) is None


@pytest.mark.asyncio
async def test_the_observed_format_actually_travels_to_the_synthesizer() -> None:
    """The seam between the two halves of U6. Detection can be perfect and emission
    can be perfect while the answer never crosses between them — and the symptom would
    be identical to having shipped neither."""
    candidates = rs.prefilter_candidates(_capture("amazon"))
    selection = await rs.select_request(
        candidates, create_message=_answering(_AMAZON_ANSWER)
    )
    assert selection.posted_at_format == PostedDateFormat("strptime", "%B %d, %Y")
    script = synthesize_recipe(
        candidates[0], selection, transport="http_json", origin_url=_AMAZON_URL
    )
    (step,) = [s for s in script["steps"] if s["op"] == "parse_date"]
    assert step["mode"] == "strptime" and step["format"] == "%B %d, %Y"


# --------------------------------------------------------------------------
# synthesize_recipe — the step that was never emitted
# --------------------------------------------------------------------------

def _selection(fmt: PostedDateFormat | None, *, field_map: dict | None = None):
    return RequestSelection(
        chosen_request_index=0,
        records_path="jobs",
        field_map=dict(_AMAZON_MAP if field_map is None else field_map),
        pagination=PaginationHint(style="offset", param="offset", page_size=10),
        posted_at_format=fmt,
    )


def _synth(selection: RequestSelection) -> dict[str, Any]:
    candidate = prefilter_candidates([_amazon_response(_amazon_body())])[0]
    return synthesize_recipe(
        candidate, selection, transport="http_json", origin_url=_AMAZON_URL
    )


def test_a_strptime_board_now_gets_its_parse_date_step() -> None:
    script = _synth(_selection(PostedDateFormat("strptime", "%B %d, %Y")))
    (step,) = [s for s in script["steps"] if s["op"] == "parse_date"]
    assert step == {
        "op": "parse_date", "field": "posted_at", "mode": "strptime",
        "format": "%B %d, %Y",
    }


def test_an_epoch_board_now_gets_its_parse_date_step() -> None:
    script = _synth(_selection(PostedDateFormat("epoch_s")))
    (step,) = [s for s in script["steps"] if s["op"] == "parse_date"]
    assert step == {"op": "parse_date", "field": "posted_at", "mode": "epoch_s"}
    assert "format" not in step


def test_the_step_lands_after_the_extraction_it_shapes() -> None:
    script = _synth(_selection(PostedDateFormat("epoch_s")))
    ops = [s["op"] for s in script["steps"]]
    assert ops.index("parse_date") > ops.index("extract_json_path")


def test_an_iso_board_gets_no_step_because_there_is_nothing_to_convert() -> None:
    script = _synth(_selection(PostedDateFormat("iso")))
    assert [s for s in script["steps"] if s["op"] == "parse_date"] == []


def test_an_unreadable_format_gets_no_step_and_the_column_stays_null() -> None:
    """The board is still perfectly trackable — it just has no posting date. Emitting
    a ``humanized`` step here would claim we identified a relative string when we only
    established that we could not read it."""
    script = _synth(_selection(None))
    assert [s for s in script["steps"] if s["op"] == "parse_date"] == []


def test_a_board_with_no_posted_at_mapping_gets_no_step() -> None:
    no_date = {k: v for k, v in _AMAZON_MAP.items() if k != "posted_at"}
    script = _synth(_selection(PostedDateFormat("epoch_s"), field_map=no_date))
    assert [s for s in script["steps"] if s["op"] == "parse_date"] == []


def test_the_synthesized_script_still_validates_on_read() -> None:
    """``synthesize_recipe`` validates on write; ``run_recipe`` validates again on
    every nightly read. A step that passed once and failed forever after is the exact
    class of bug validate-on-read exists to surface."""
    script = _synth(_selection(PostedDateFormat("epoch_s")))
    validate_recipe(script, transport="http_json", oracle_kind=script["oracle"]["kind"])


# --------------------------------------------------------------------------
# recipe_schema — the widened closed mode set
# --------------------------------------------------------------------------

def _script_with(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://x.example/j", "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "t", "url": "u"}},
            step,
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "none"},
    }


@pytest.mark.parametrize("mode", PARSE_DATE_MODES)
def test_every_declared_mode_is_accepted(mode: str) -> None:
    validate_recipe(_script_with(_step(mode, "%Y" if mode == "strptime" else None)))


@pytest.mark.parametrize("mode", ["epoch", "epoch_seconds", "unix", "EPOCH_S", ""])
def test_a_mode_outside_the_closed_set_is_still_refused(mode: str) -> None:
    with pytest.raises(RecipeError):
        validate_recipe(_script_with(_step(mode)))


def test_strptime_still_requires_its_format() -> None:
    with pytest.raises(RecipeError):
        validate_recipe(_script_with(_step("strptime")))


# --------------------------------------------------------------------------
# end to end, on a Microsoft-shaped payload
# --------------------------------------------------------------------------

_MS_RECORDS = [
    {"id": str(i), "name": f"Engineer {i}", "positionUrl": f"/job/{i}",
     "postedTs": _MS_EPOCH_S + i}
    for i in range(100)
]


def _ms_script(with_step: bool) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        {"op": "fetch", "method": "GET",
         "url": "https://apply.careers.microsoft.com/api/pcsx/search", "headers": {}},
        {"op": "extract_json_path", "records_path": "data.positions",
         "fields": {"id": "id", "title": "name", "posted_at": "postedTs",
                    "url": "https://apply.careers.microsoft.com{positionUrl}"}},
    ]
    if with_step:
        steps.append({"op": "parse_date", "field": "posted_at", "mode": "epoch_s"})
    steps += [{"op": "dedupe_key", "field": "id"}, {"op": "assert_unique", "field": "id"}]
    return {
        "script_version": 1, "transport": "http_json", "expected_min_jobs": 1,
        "base_url": "https://apply.careers.microsoft.com",
        "steps": steps, "oracle": {"kind": "none"},
    }


def _client(records: list[dict]) -> httpx.Client:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"positions": records}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_microsoft_shaped_payload_writes_a_real_date_on_every_row() -> None:
    """The whole point of U6, measured the way the symptom was: share of rows that end
    up with a usable date. The stored recipe scored 0 of 2,217 on the real board."""
    rows, _ = run_recipe(_ms_script(True), _client(_MS_RECORDS), transport="http_json",
                         oracle_kind="none")
    dated = [r for r in rows if isinstance(r.get("posted_at"), str)
             and r["posted_at"].startswith("2026-")]
    assert len(rows) == 100
    assert len(dated) / len(rows) >= 0.95


def test_without_the_step_the_same_payload_carries_a_raw_epoch_instead() -> None:
    """The BEFORE state, pinned so the fix cannot silently regress to it: the runner
    hands ``recipe_rows`` an int, which becomes the string ``'1787617881'``, which
    ``datetime.fromisoformat`` can only raise on."""
    rows, _ = run_recipe(_ms_script(False), _client(_MS_RECORDS), transport="http_json",
                         oracle_kind="none")
    assert all(isinstance(r["posted_at"], int) for r in rows)


def test_a_board_publishing_no_date_writes_null_and_never_now() -> None:
    records = [{"id": str(i), "name": "SWE", "positionUrl": f"/j/{i}"} for i in range(20)]
    rows, _ = run_recipe(_ms_script(True), _client(records), transport="http_json",
                         oracle_kind="none")
    assert len(rows) == 20
    assert all(r["posted_at"] is None for r in rows)


def test_an_unparseable_value_writes_null_and_the_harvest_still_returns_every_row() -> None:
    """RAISES-never-empty end to end: 20 rows in, 20 rows out, 20 NULL dates — not a
    raise, not a short harvest, and above all not ``now()``."""
    records = [{"id": str(i), "name": "SWE", "positionUrl": f"/j/{i}",
                "postedTs": "sometime last week"} for i in range(20)]
    rows, evidence = run_recipe(_ms_script(True), _client(records),
                                transport="http_json", oracle_kind="none")
    assert len(rows) == 20
    assert all(r["posted_at"] is None for r in rows)
    assert evidence.transport_ok is True


def test_a_genuinely_empty_board_still_raises_rather_than_returning_no_rows() -> None:
    """The invariant date handling must not erode: zero records is a FAILED run, never
    a successful empty harvest — that is the 2026-03-29 mass-closure class."""
    with pytest.raises(RecipeExecutionError):
        run_recipe(_ms_script(True), _client([]), transport="http_json",
                   oracle_kind="none")
