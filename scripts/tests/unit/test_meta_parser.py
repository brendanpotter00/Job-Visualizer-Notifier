"""Unit tests for the Meta parser — the load-bearing pure logic.

Covers shape-based selection (incl. a renamed wrapper), parse_list_job, dedupe,
job_count picking, the truncation guard, the raise-on-empty diagnosis, and the
settle poll. No browser, no network.
"""

import copy
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from meta_jobs_scraper.config import ALL_JOBS_KEY, FEATURED_JOBS_KEY
from meta_jobs_scraper.parser import (
    MetaCaptureError,
    _advertised_job_count,
    _capture_stats,
    _container_jobs,
    _decode_graphql_payload,
    _empty_capture_reason,
    _finalize_capture,
    _has_job_payload,
    _is_truncated,
    _iter_job_containers,
    _iter_job_counts,
    _join_strings,
    _reduce_payloads,
    _SettlePoll,
    build_job_url,
    parse_list_job,
)

WRAPPER_KEY = "job_search_with_featured_jobs_v2"


# --- fixtures/helpers ---------------------------------------------------------

def _nonempty_payload(job_id="x", title="Software Engineer"):
    return {"data": {"w": {ALL_JOBS_KEY: [{"id": job_id, "title": title}]}}}


def _empty_strip_payload():
    return {"data": {"w": {FEATURED_JOBS_KEY: []}}}


# --- build_job_url ------------------------------------------------------------

class TestBuildJobUrl:
    def test_builds(self):
        assert build_job_url("123") == "https://www.metacareers.com/profile/job_details/123"


# --- _join_strings ------------------------------------------------------------

class TestJoinStrings:
    def test_list_of_strings(self):
        assert _join_strings(["A", "B"]) == "A, B"

    def test_list_of_dicts_title_or_name(self):
        assert _join_strings([{"title": "A"}, {"name": "B"}]) == "A, B"

    def test_mixed(self):
        assert _join_strings(["A", {"title": "B"}]) == "A, B"

    @pytest.mark.parametrize("val", [None, [], "notalist", [{}], [123]])
    def test_none_and_empty(self, val):
        assert _join_strings(val) is None


# --- parse_list_job -----------------------------------------------------------

class TestParseListJob:
    def test_full_job(self):
        card = parse_list_job(
            {
                "id": 42,
                "title": "Software Engineer, Infra",
                "locations": ["Menlo Park, CA"],
                "teams": [{"title": "Infrastructure"}],
                "sub_teams": [{"title": "Data Platform"}],
            }
        )
        assert card is not None
        assert card["id"] == "42"  # coerced to str
        assert card["title"] == "Software Engineer, Infra"
        assert card["location"] == "Menlo Park, CA"
        assert card["department"] == "Infrastructure — Data Platform"
        assert card["job_url"] == "https://www.metacareers.com/profile/job_details/42"
        assert card["company"] == "meta"
        assert card["raw"]["id"] == 42

    def test_department_teams_only(self):
        card = parse_list_job({"id": "1", "title": "SWE", "teams": ["Ads"]})
        assert card["department"] == "Ads"

    def test_department_sub_teams_only(self):
        card = parse_list_job({"id": "1", "title": "SWE", "sub_teams": ["GenAI"]})
        assert card["department"] == "GenAI"

    def test_department_none_when_absent(self):
        card = parse_list_job({"id": "1", "title": "SWE"})
        assert card["department"] is None

    def test_no_posted_date_key(self):
        """Meta's list query carries no date — the card must not invent one."""
        card = parse_list_job({"id": "1", "title": "SWE"})
        assert "posted_on" not in card
        assert "posted_at" not in card

    def test_missing_id_dropped(self):
        assert parse_list_job({"title": "SWE"}) is None
        assert parse_list_job({"id": "", "title": "SWE"}) is None

    def test_missing_or_bad_title_dropped(self):
        assert parse_list_job({"id": "1"}) is None
        assert parse_list_job({"id": "1", "title": ""}) is None
        assert parse_list_job({"id": "1", "title": 123}) is None

    def test_non_dict_dropped(self):
        assert parse_list_job("nope") is None


# --- shape-based selection ----------------------------------------------------

class TestShapeBasedSelection:
    def test_finds_container_under_real_wrapper(self, meta_graphql_capture):
        data = meta_graphql_capture[0]["data"]
        containers = list(_iter_job_containers(data))
        assert len(containers) == 1
        assert ALL_JOBS_KEY in containers[0]

    def test_renamed_wrapper_still_found(self, meta_graphql_capture):
        """Rename the wrapper to ..._v3 — selection is by SHAPE, not name."""
        renamed = copy.deepcopy(meta_graphql_capture)
        payload = renamed[0]["data"]
        payload["job_search_with_featured_jobs_v3"] = payload.pop(WRAPPER_KEY)
        cards = _reduce_payloads(renamed)
        ids = {c["id"] for c in cards}
        assert ids == {"j1", "j2", "j3", "j5"}

    def test_does_not_stop_at_empty_outer_strip(self):
        """An outer empty featured_jobs strip must not hide a nested container."""
        node = {
            "outer": {
                FEATURED_JOBS_KEY: [],
                "inner": {ALL_JOBS_KEY: [{"id": "1", "title": "SWE"}]},
            }
        }
        containers = list(_iter_job_containers(node))
        # both the outer (empty featured) and the inner (real all_jobs) qualify
        assert len(containers) == 2
        assert any(_container_jobs(c) for c in containers)

    def test_container_jobs_ignores_non_lists(self):
        assert _container_jobs({ALL_JOBS_KEY: "x", FEATURED_JOBS_KEY: None}) == []


# --- _reduce_payloads (dedupe) ------------------------------------------------

class TestReducePayloads:
    def test_distinct_by_id_dedupes_featured_duplicate(self, meta_graphql_capture):
        cards = _reduce_payloads(meta_graphql_capture)
        ids = [c["id"] for c in cards]
        assert ids == ["j1", "j2", "j3", "j5"]  # j1 featured-dup collapsed
        assert len(ids) == len(set(ids))

    def test_drops_missing_id_and_title(self, meta_graphql_capture):
        cards = _reduce_payloads(meta_graphql_capture)
        # the no-title and no-id entries never appear
        assert all(c["title"] for c in cards)


# --- job_count picking --------------------------------------------------------

class TestJobCount:
    def test_iter_yields_all_counts(self):
        node = {"a": {"job_count": 6}, "b": {"open_job_count": 890}}
        assert sorted(_iter_job_counts(node)) == [6, 890]

    def test_ignores_bool(self):
        assert list(_iter_job_counts({"job_count": True})) == []

    def test_ignores_non_positive(self):
        assert list(_iter_job_counts({"job_count": 0})) == []
        assert list(_iter_job_counts({"job_count": -5})) == []

    def test_accepts_suffixed_variant(self):
        assert list(_iter_job_counts({"total_job_count": 42})) == [42]

    def test_advertised_takes_max(self):
        payloads = [{"data": {"a": {"job_count": 6}, "b": {"job_count": 890}}}]
        assert _advertised_job_count(payloads) == 890

    def test_advertised_none_and_warns_when_absent(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _advertised_job_count([{"data": {"x": {"y": 1}}}])
        assert result is None
        assert "no 'job_count' scalar" in caplog.text or "job_count" in caplog.text


# --- _is_truncated ------------------------------------------------------------

class TestIsTruncated:
    def test_below_ratio_is_truncated(self):
        assert _is_truncated(80, 100) is True   # 80 < 90
        assert _is_truncated(1, 100) is True

    def test_at_or_above_ratio_is_not(self):
        assert _is_truncated(90, 100) is False
        assert _is_truncated(100, 100) is False

    def test_none_advertised_disables_guard(self):
        assert _is_truncated(1, None) is False


# --- _decode_graphql_payload --------------------------------------------------

class TestDecodeGraphqlPayload:
    def test_valid_dict(self):
        assert _decode_graphql_payload('{"a": 1}') == {"a": 1}

    def test_valid_non_dict_is_none(self):
        assert _decode_graphql_payload("[1, 2, 3]") is None

    def test_invalid_json_small_is_none(self):
        assert _decode_graphql_payload("not json") is None

    def test_suspicious_undecodable_warns(self, caplog):
        """A body that mentions all_jobs but won't parse is warned, not silent."""
        with caplog.at_level(logging.WARNING):
            result = _decode_graphql_payload('{"all_jobs": broken')
        assert result is None
        assert "could not be JSON-decoded" in caplog.text

    def test_large_undecodable_warns(self, caplog):
        big = "x" * 60_000  # >= LARGE_BODY_BYTES, invalid JSON
        with caplog.at_level(logging.WARNING):
            result = _decode_graphql_payload(big)
        assert result is None
        assert "could not be JSON-decoded" in caplog.text


# --- _has_job_payload ---------------------------------------------------------

class TestHasJobPayload:
    def test_true_for_nonempty(self):
        assert _has_job_payload([_nonempty_payload()]) is True

    def test_false_for_empty_strip(self):
        assert _has_job_payload([_empty_strip_payload()]) is False

    def test_false_for_nothing(self):
        assert _has_job_payload([]) is False


# --- _empty_capture_reason (five branches) ------------------------------------

class TestEmptyCaptureReason:
    def test_jobs_present_none_parsed(self):
        msg = _empty_capture_reason(3, None, containers_seen=1, jobs_seen=5)
        assert "parsed none" in msg
        assert "5" in msg

    def test_empty_board(self):
        msg = _empty_capture_reason(3, None, containers_seen=1, jobs_seen=0)
        assert "empty" in msg

    def test_no_graphql_no_nav_error(self):
        msg = _empty_capture_reason(0, None)
        assert "zero GraphQL POST responses" in msg

    def test_no_graphql_with_nav_error(self):
        msg = _empty_capture_reason(0, RuntimeError("boom"))
        assert "no GraphQL traffic" in msg
        assert "boom" in msg

    def test_graphql_but_renamed_arrays(self):
        msg = _empty_capture_reason(4, None)
        assert "renamed the job-search payload" in msg


# --- _finalize_capture: raise on empty (one per branch) -----------------------

class TestFinalizeRaiseOnEmpty:
    def test_renamed_arrays_raises(self):
        captured = [{"data": {"other": {"unrelated": []}}}]
        with pytest.raises(MetaCaptureError, match="renamed the job-search payload"):
            _finalize_capture(captured, graphql_seen=1, nav_error=None)

    def test_empty_board_raises(self):
        captured = [{"data": {"w": {ALL_JOBS_KEY: []}}}]
        with pytest.raises(MetaCaptureError, match="empty"):
            _finalize_capture(captured, graphql_seen=1, nav_error=None)

    def test_jobs_present_none_parsed_raises(self):
        captured = [{"data": {"w": {ALL_JOBS_KEY: [{"foo": "bar"}]}}}]
        with pytest.raises(MetaCaptureError, match="parsed none"):
            _finalize_capture(captured, graphql_seen=1, nav_error=None)

    def test_no_graphql_raises(self):
        with pytest.raises(MetaCaptureError, match="zero GraphQL POST responses"):
            _finalize_capture([], graphql_seen=0, nav_error=None)

    def test_no_graphql_with_nav_error_raises(self):
        with pytest.raises(MetaCaptureError, match="no GraphQL traffic"):
            _finalize_capture([], graphql_seen=0, nav_error=RuntimeError("nav"))


# --- _finalize_capture: truncation guard --------------------------------------

class TestFinalizeTruncation:
    def test_truncated_raises_naming_both_numbers(self):
        captured = [
            {"data": {"w": {ALL_JOBS_KEY: [{"id": "a", "title": "Software Engineer"}]}}},
            {"data": {"f": {"job_count": 100}}},
        ]
        with pytest.raises(MetaCaptureError) as exc:
            _finalize_capture(captured, graphql_seen=2, nav_error=None)
        assert "1" in str(exc.value) and "100" in str(exc.value)

    def test_missing_count_disables_guard(self):
        """No job_count → guard off → a small-but-real capture is returned."""
        captured = [{"data": {"w": {ALL_JOBS_KEY: [{"id": "a", "title": "SWE"}]}}}]
        cards = _finalize_capture(captured, graphql_seen=1, nav_error=None)
        assert len(cards) == 1


# --- _finalize_capture: happy path --------------------------------------------

class TestFinalizeHappyPath:
    def test_returns_parsed_cards(self, meta_graphql_capture):
        cards = _finalize_capture(
            meta_graphql_capture, graphql_seen=2, nav_error=None
        )
        assert {c["id"] for c in cards} == {"j1", "j2", "j3", "j5"}

    def test_nav_error_but_nonempty_does_not_raise(self, meta_graphql_capture):
        """A recovered nav error must not fail an otherwise-good capture."""
        cards = _finalize_capture(
            meta_graphql_capture, graphql_seen=2, nav_error=RuntimeError("networkidle")
        )
        assert len(cards) == 4


# --- _capture_stats -----------------------------------------------------------

class TestCaptureStats:
    def test_counts_containers_and_jobs(self, meta_graphql_capture):
        containers, jobs = _capture_stats(meta_graphql_capture)
        assert containers == 1
        # all_jobs (5) + featured_jobs (2) = 7 raw entries in the one container
        assert jobs == 7


# --- _SettlePoll --------------------------------------------------------------

class TestSettlePoll:
    def test_wait_does_not_stop_on_empty_array(self):
        poll = _SettlePoll(wait_polls=5, drain_polls=3, stable_polls=2)
        empty = [_empty_strip_payload()]
        # first four polls: budget not exhausted, no job payload → keep waiting
        for _ in range(4):
            assert poll.should_stop(empty) is False
        # fifth: wait budget exhausted → stop (caller then raises)
        assert poll.should_stop(empty) is True
        assert poll.draining is False

    def test_stops_once_nonempty_lands_then_stable(self):
        poll = _SettlePoll(wait_polls=100, drain_polls=100, stable_polls=1)
        payloads = [_nonempty_payload()]
        # transition into draining, does not stop yet
        assert poll.should_stop(payloads) is False
        assert poll.draining is True
        # length stable for stable_polls=1 → stop
        assert poll.should_stop(payloads) is True

    def test_drain_capped_by_drain_polls(self):
        poll = _SettlePoll(wait_polls=100, drain_polls=2, stable_polls=100)
        base = _nonempty_payload()
        lst = [base]
        assert poll.should_stop(lst) is False  # transition
        lst = [base, base]
        assert poll.should_stop(lst) is False  # drained=1, len changed → no stable
        lst = [base, base, base]
        assert poll.should_stop(lst) is True   # drained=2 >= drain_polls
