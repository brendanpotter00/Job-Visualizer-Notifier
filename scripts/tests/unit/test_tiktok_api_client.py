"""
Unit tests for the TikTok api_client.

The headline case is the envelope contract: TikTok answers HTTP 200 with a
non-zero ``code`` on payload-level errors, and returning partial results there
would let the consecutive-misses lifecycle close the whole company during a
sustained upstream outage.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tiktok_jobs_scraper import api_client
from tiktok_jobs_scraper.api_client import (
    JobSearchError,
    _parse_job_from_search,
    _parse_search_response,
    build_search_body,
    combine_description,
    fetch_search_results,
    flatten_location,
    format_department,
    get_job_url,
    get_search_url,
)


class TestFetchJs:
    """The in-page fetch payload — pinned because it cannot be unit-executed."""

    def test_is_a_post_with_serialised_body(self):
        js = api_client._FETCH_JS
        assert "method: 'POST'" in js
        assert "JSON.stringify(body)" in js

    def test_is_double_bounded(self):
        js = api_client._FETCH_JS
        for token in ("AbortController", "ctrl.signal", "timeoutMs", "setTimeout", "clearTimeout"):
            assert token in js, f"missing {token}"
        assert api_client._FETCH_BROWSER_TIMEOUT_MS == 15_000
        assert api_client._FETCH_OUTER_TIMEOUT_S == 20.0

    def test_website_path_header_present(self):
        """Without this header the edge answers HTTP 400."""
        assert api_client._JSON_HEADERS["website-path"] == "tiktok"
        assert api_client._JSON_HEADERS["content-type"] == "application/json"

    def test_no_literal_control_bytes(self):
        stray = [c for c in api_client._FETCH_JS if ord(c) < 0x20 and c != "\n"]
        assert not stray, f"literal control chars in _FETCH_JS: {stray!r}"


class TestBuildSearchBody:
    def test_shape(self):
        body = build_search_body("software engineer", 300)
        assert body["limit"] == 100
        assert body["offset"] == 300
        assert body["keyword"] == "software engineer"

    def test_all_filter_lists_empty(self):
        """location_code_list must stay empty — it takes city codes, not countries."""
        body = build_search_body("x", 0)
        for key in (
            "recruitment_id_list",
            "job_category_id_list",
            "subject_id_list",
            "location_code_list",
        ):
            assert body[key] == [], f"{key} should be empty"

    def test_search_url(self):
        assert get_search_url() == (
            "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
        )


class TestFlattenLocation:
    def test_full_three_level_chain(self, tiktok_raw_job):
        assert flatten_location(tiktok_raw_job["city_info"]) == (
            "San Jose, California, United States of America"
        )

    def test_two_level_chain(self):
        ci = {"en_name": "Tokyo", "parent": {"en_name": "Japan", "parent": None}}
        assert flatten_location(ci) == "Tokyo, Japan"

    def test_skips_blank_levels(self):
        ci = {
            "en_name": "Singapore",
            "parent": {"en_name": "   ", "parent": {"en_name": "Singapore", "parent": None}},
        }
        assert flatten_location(ci) == "Singapore, Singapore"

    def test_null_en_name_everywhere(self):
        assert flatten_location({"en_name": None, "parent": None}) is None

    def test_non_dict(self):
        assert flatten_location(None) is None
        assert flatten_location("San Jose") is None


class TestFormatDepartment:
    def test_nested(self, tiktok_raw_job):
        assert format_department(tiktok_raw_job["job_category"]) == "R&D / Backend"

    def test_flat(self):
        assert format_department({"en_name": "Operations", "parent": None}) == "Operations"

    def test_blank_parent_falls_back_to_child(self):
        assert format_department({"en_name": "Design", "parent": {"en_name": "  "}}) == "Design"

    def test_blank_child(self):
        assert format_department({"en_name": "  ", "parent": None}) is None

    def test_non_dict(self):
        assert format_department(None) is None


class TestCombineDescription:
    def test_joins_both_blocks(self, tiktok_raw_job):
        out = combine_description(tiktok_raw_job)
        assert "About the team" in out
        assert "Minimum Qualifications" in out
        assert "\n\n" in out

    def test_description_only(self):
        assert combine_description({"description": "just this"}) == "just this"

    def test_requirement_only(self):
        assert combine_description({"requirement": "just reqs"}) == "just reqs"

    def test_both_empty(self):
        assert combine_description({}) is None
        assert combine_description({"description": "  ", "requirement": None}) is None

    def test_no_html_stripping_needed(self):
        """TikTok returns plain text; angle brackets must survive verbatim."""
        assert combine_description({"description": "latency < 100ms"}) == "latency < 100ms"


class TestParseSearchResponse:
    def test_happy_path(self, tiktok_search_response):
        out = _parse_search_response(tiktok_search_response)
        assert out["raw_count"] == 2
        assert len(out["jobs"]) == 2
        assert out["total"] == 716

    def test_non_zero_code_raises(self):
        """HTTP 200 + code!=0 must RAISE, never return partial results."""
        payload = {"code": 1001, "message": "rate limited", "data": None}
        with pytest.raises(JobSearchError) as exc:
            _parse_search_response(payload)
        assert "1001" in str(exc.value)
        assert "rate limited" in str(exc.value)

    def test_non_dict_payload_raises(self):
        with pytest.raises(JobSearchError):
            _parse_search_response(["nope"])

    def test_missing_code_raises(self):
        with pytest.raises(JobSearchError):
            _parse_search_response({"data": {"job_post_list": []}})

    def test_null_data_with_code_zero_is_empty_not_error(self):
        out = _parse_search_response({"code": 0, "data": None})
        assert out["raw_count"] == 0
        assert out["jobs"] == []

    def test_skips_missing_id_with_warning(self, caplog):
        payload = {"code": 0, "data": {"job_post_list": [{"title": "SDE"}, {"id": "1", "title": "SDE"}]}}
        with caplog.at_level("WARNING"):
            out = _parse_search_response(payload)
        assert out["raw_count"] == 2
        assert len(out["jobs"]) == 1
        assert "missing id" in caplog.text

    def test_skips_missing_title_with_warning(self, caplog):
        payload = {"code": 0, "data": {"job_post_list": [{"id": "1"}, {"id": "2", "title": "SDE"}]}}
        with caplog.at_level("WARNING"):
            out = _parse_search_response(payload)
        assert len(out["jobs"]) == 1
        assert "missing title" in caplog.text

    def test_non_int_count_becomes_none(self):
        payload = {"code": 0, "data": {"job_post_list": [], "count": "716"}}
        assert _parse_search_response(payload)["total"] is None


class TestParseJobFromSearch:
    def test_card_shape(self, tiktok_raw_job):
        card = _parse_job_from_search(tiktok_raw_job)
        assert card["id"] == "7613184212766607621"
        assert card["job_url"] == "https://lifeattiktok.com/search/7613184212766607621"
        assert card["location"] == "San Jose, California, United States of America"
        assert card["department"] == "R&D / Backend"
        assert card["recruit_type"] == "Regular"
        assert card["job_code"] == "A07200"

    def test_posted_date_is_always_none(self, tiktok_raw_job):
        """TikTok's payload has no posted/created/published field at all."""
        assert _parse_job_from_search(tiktok_raw_job)["posted_date"] is None

    def test_id_is_stringified(self):
        card = _parse_job_from_search({"id": 7613184212766607621, "title": "SDE"})
        assert card["id"] == "7613184212766607621"
        assert isinstance(card["id"], str)

    def test_recruit_type_non_dict_tolerated(self, tiktok_raw_job):
        tiktok_raw_job["recruit_type"] = "Regular"
        assert _parse_job_from_search(tiktok_raw_job)["recruit_type"] is None

    def test_get_job_url(self):
        assert get_job_url("123") == "https://lifeattiktok.com/search/123"


@pytest.mark.asyncio
class TestFetchSearchResults:
    async def test_success(self, tiktok_search_response):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=tiktok_search_response)
        out = await fetch_search_results(page, "software engineer", 0)
        assert len(out["jobs"]) == 2
        assert out["total"] == 716

    async def test_passes_headers_body_and_timeout_into_js(self, tiktok_search_response):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=tiktok_search_response)
        await fetch_search_results(page, "software engineer", 200)

        _, arg = page.evaluate.call_args[0]
        assert arg["headers"]["website-path"] == "tiktok"
        assert arg["timeoutMs"] == api_client._FETCH_BROWSER_TIMEOUT_MS
        assert arg["body"]["offset"] == 200
        assert arg["body"]["keyword"] == "software engineer"
        assert arg["url"].endswith("/api/v1/public/supplier/search/job/posts")

    async def test_envelope_error_propagates_as_job_search_error(self):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={"code": 500, "message": "boom", "data": None})
        with pytest.raises(JobSearchError) as exc:
            await fetch_search_results(page, "software engineer", 0)
        # Must surface the envelope code, not be rewrapped as a generic failure
        assert "500" in str(exc.value)

    async def test_outer_timeout_becomes_job_search_error(self):
        page = AsyncMock()

        async def _hang(*_a, **_k):
            await asyncio.sleep(5)

        page.evaluate = _hang
        with patch.object(api_client, "_FETCH_OUTER_TIMEOUT_S", 0.05):
            with pytest.raises(JobSearchError) as exc:
                await fetch_search_results(page, "software engineer", 0)
        assert "timed out" in str(exc.value)

    async def test_generic_error_becomes_job_search_error(self):
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("HTTP 400"))
        with pytest.raises(JobSearchError) as exc:
            await fetch_search_results(page, "software engineer", 0)
        assert "400" in str(exc.value)
