"""
Unit tests for the Amazon api_client.

The headline cases here are the two live-verified hazards:
  * V8's JSON.parse rejects raw control bytes, so `_FETCH_JS` must not use
    `r.json()` and must sanitise on failure.
  * A loose `<[^>]+>` tag regex destroys prose containing a literal "<".
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amazon_jobs_scraper import api_client
from amazon_jobs_scraper.api_client import (
    JobSearchError,
    _parse_job_from_search,
    _parse_search_response,
    build_search_api_url,
    combine_description,
    extract_location,
    fetch_search_results,
    get_job_url,
    parse_posted_date,
    strip_html,
)


# ---------------------------------------------------------------- _FETCH_JS

class TestFetchJs:
    """The in-page fetch payload.

    Most assertions here are substring checks, which cannot catch a syntax
    error — and every integration test mocks ``page.evaluate``, so before
    ``test_fetch_js_is_syntactically_valid_javascript`` the only thing that ever
    executed this JS was the e2e suite, which ``pytest.ini`` excludes
    (``-m "not e2e"``) and which runs twice a week. A broken ``_FETCH_JS`` could
    merge green and leave the scraper dead for days.
    """

    def test_fetch_js_is_syntactically_valid_javascript(self):
        """Actually parse the JS instead of grepping it.

        Skips rather than fails where node is unavailable, so the suite stays
        runnable without a JS toolchain; CI has node.
        """
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")

        # _FETCH_JS is an arrow-function expression; wrap it so `node --check`
        # sees a complete program (a bare arrow function is a valid expression
        # statement only when parenthesised).
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write("const fn = (\n%s\n);\n" % api_client._FETCH_JS)
            path = fh.name
        try:
            proc = subprocess.run(
                [node, "--check", path], capture_output=True, text=True, timeout=30
            )
        finally:
            os.unlink(path)

        assert proc.returncode == 0, (
            f"_FETCH_JS is not valid JavaScript:\n{proc.stderr}"
        )

    def test_uses_text_not_json(self):
        """r.json() would throw on Amazon's control bytes; r.text() does not."""
        assert "await r.text()" in api_client._FETCH_JS
        assert "r.json()" not in api_client._FETCH_JS

    def test_is_double_bounded(self):
        js = api_client._FETCH_JS
        for token in ("AbortController", "ctrl.signal", "timeoutMs", "setTimeout", "clearTimeout"):
            assert token in js, f"missing {token}"
        assert api_client._FETCH_BROWSER_TIMEOUT_MS == 15_000
        assert api_client._FETCH_OUTER_TIMEOUT_S == 20.0

    def test_sanitiser_covers_control_ranges(self):
        js = api_client._FETCH_JS
        assert r"\u0009\u000A\u000D" in js, "tab/LF/CR must map to a space"
        assert r"\u0000-\u001F" in js, "remaining C0 controls must be dropped"

    def test_no_literal_control_bytes_in_js(self):
        """A literal newline inside a JS regex literal is a syntax error."""
        body = api_client._FETCH_JS
        stray = [c for c in body if ord(c) < 0x20 and c != "\n"]
        assert not stray, f"literal control chars leaked into _FETCH_JS: {stray!r}"

    def test_headers_are_json_accept_only(self):
        # Content-Type is meaningless on a GET; Amazon needs only Accept.
        assert api_client._JSON_HEADERS == {"Accept": "application/json"}

    def test_python_mirror_of_sanitiser_makes_payload_parseable(self, amazon_dirty_json_text):
        """Pin the sanitiser *semantics* even though the JS itself is mocked."""
        with pytest.raises(json.JSONDecodeError):
            json.loads(amazon_dirty_json_text)

        cleaned = re.sub(r"[\x09\x0a\x0d]", " ", amazon_dirty_json_text)
        cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
        parsed = json.loads(cleaned)
        assert parsed["jobs"][0]["description"] == "ab"

    def test_sanitiser_keeps_words_separated(self):
        """Tab/LF/CR become a space so "one\\ntwo" never becomes "onetwo"."""
        raw = '{"a": "one\ntwo"}'
        cleaned = re.sub(r"[\x09\x0a\x0d]", " ", raw)
        cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
        assert json.loads(cleaned)["a"] == "one two"


# ------------------------------------------------------------- strip_html

class TestStripHtml:
    def test_none_and_empty(self):
        assert strip_html(None) is None
        assert strip_html("") is None
        assert strip_html("<br/>") is None

    def test_br_becomes_newline(self):
        assert strip_html("one<br/>two") == "one\ntwo"

    def test_inline_tags_removed(self):
        assert strip_html('<span>a</span> <a href="http://x">b</a>') == "a b"

    def test_entities_unescaped(self):
        assert strip_html("R&amp;D") == "R&D"

    def test_preserves_literal_less_than_in_prose(self):
        """Regression: the loose `<[^>]+>` pattern ate this entire sentence.

        Live Amazon job 10490591 carries exactly this shape.
        """
        raw = "Perf: P99 < 1 second at 40 TPS; P99 < 100ms for serving<br/>Next"
        out = strip_html(raw)
        assert "< 1 second" in out
        assert "< 100ms" in out
        assert out == "Perf: P99 < 1 second at 40 TPS; P99 < 100ms for serving\nNext"

    def test_no_residual_markup(self):
        out = strip_html("<div><p>a</p><ul><li>b</li></ul></div>")
        assert "<" not in out and ">" not in out

    def test_collapses_excess_blank_lines(self):
        assert "\n\n\n" not in (strip_html("a<br/><br/><br/><br/>b") or "")


class TestCombineDescription:
    def test_joins_three_sections_in_order(self, amazon_raw_job):
        out = combine_description(amazon_raw_job)
        assert out.index("world class advertising") < out.index("3+ years")
        assert out.index("3+ years") < out.index("AWS")
        assert "\n\n" in out

    def test_skips_missing_middle_section_without_double_blank(self):
        out = combine_description({"description": "a", "preferred_qualifications": "c"})
        assert out == "a\n\nc"

    def test_all_empty_returns_none(self):
        assert combine_description({}) is None
        assert combine_description({"description": "", "basic_qualifications": None}) is None


# --------------------------------------------------------- parse_posted_date

class TestParsePostedDate:
    def test_double_space_english_date(self):
        """Amazon really does send two spaces after the month."""
        assert parse_posted_date("August  8, 2026") == "2026-08-08"

    def test_single_space_english_date(self):
        assert parse_posted_date("May 14, 2026") == "2026-05-14"

    def test_naive_result_is_date_only(self):
        """10 chars, not a UTC-midnight timestamp — see the docstring."""
        assert len(parse_posted_date("May 14, 2026")) == 10

    def test_tz_aware_normalised_to_utc(self):
        assert parse_posted_date("2026-05-15T15:00:00-04:00") == "2026-05-15T19:00:00+00:00"

    def test_malformed_warns_and_returns_none(self, caplog):
        with caplog.at_level("WARNING"):
            assert parse_posted_date("not a date at all") is None
        assert "could not parse posted_date" in caplog.text

    def test_missing_returns_none_without_warning(self, caplog):
        with caplog.at_level("WARNING"):
            assert parse_posted_date(None) is None
            assert parse_posted_date("") is None
        assert "could not parse" not in caplog.text


# ------------------------------------------------------------ small helpers

class TestHelpers:
    def test_extract_location_prefers_normalized(self):
        assert extract_location(
            {"normalized_location": "Seattle, Washington, USA", "location": "US, WA, Seattle"}
        ) == "Seattle, Washington, USA"

    def test_extract_location_falls_back(self):
        assert extract_location({"location": "US, WA, Seattle"}) == "US, WA, Seattle"

    def test_extract_location_none(self):
        assert extract_location({}) is None

    def test_get_job_url(self):
        assert get_job_url("/en/jobs/1/x") == "https://www.amazon.jobs/en/jobs/1/x"

    def test_get_job_url_passthrough_absolute(self):
        assert get_job_url("https://www.amazon.jobs/en/jobs/1/x") == \
            "https://www.amazon.jobs/en/jobs/1/x"

    def test_get_job_url_empty(self):
        assert get_job_url("") == "https://www.amazon.jobs"

    def test_build_search_api_url_encodes_query(self):
        url = build_search_api_url("software engineer", 200)
        assert "base_query=software+engineer" in url
        assert "offset=200" in url
        assert "result_limit=100" in url
        assert "sort=recent" in url
        assert "country=USA" in url
        assert url.startswith("https://www.amazon.jobs/en/search.json?")


# ----------------------------------------------------------- response parse

class TestParseSearchResponse:
    def test_happy_path(self, amazon_search_response):
        out = _parse_search_response(amazon_search_response)
        assert out["raw_count"] == 2
        assert len(out["jobs"]) == 2
        assert out["hits"] == 1303
        assert out["jobs"][0]["id"] == "10496449"

    def test_jobs_null_parses_as_empty_but_surfaces_the_error(self, caplog):
        """result_limit>100 really answers 200 with jobs: null.

        The parser stays non-fatal here, but it MUST hand the error string back
        to the caller: ``scrape_query`` raises on a non-null ``error`` rather
        than reading raw_count==0 as a clean end of results. An earlier version
        dropped the error on the floor and silently truncated the run.
        """
        payload = {
            "error": "Result limit cannot be greater than 100",
            "hits": 0,
            "jobs": None,
        }
        with caplog.at_level("WARNING"):
            out = _parse_search_response(payload)
        assert out["raw_count"] == 0
        assert out["jobs"] == []
        assert out["error"] == "Result limit cannot be greater than 100"
        assert "Result limit cannot be greater than 100" in caplog.text

    def test_non_list_jobs_raises_rather_than_reading_as_empty(self):
        """A `jobs` that is neither list nor null is a schema break.

        Coercing it to [] made an envelope change look like "no more results" —
        with no log line at all.
        """
        payload = {"jobs": {"items": [{"id_icims": "1", "title": "SDE"}]}, "hits": 1300}
        with pytest.raises(JobSearchError, match="expected list or null"):
            _parse_search_response(payload)

    def test_non_dict_rows_are_not_misreported_as_missing_title(self, caplog):
        """A shape change must not send the reader hunting the `title` field."""
        payload = {"jobs": ["a string", 42, None], "hits": 3}
        with caplog.at_level("ERROR"):
            out = _parse_search_response(payload)
        assert out["skipped_not_dict"] == 3
        assert out["skipped_missing_title"] == 0
        assert out["skipped_missing_id"] == 0
        assert "not objects" in caplog.text

    def test_skips_missing_id_with_warning(self, caplog):
        payload = {"jobs": [{"title": "SDE"}, {"id_icims": "1", "title": "SDE"}]}
        with caplog.at_level("WARNING"):
            out = _parse_search_response(payload)
        assert out["raw_count"] == 2
        assert len(out["jobs"]) == 1
        assert out["skipped_missing_id"] == 1
        assert "missing id_icims" in caplog.text

    def test_skips_missing_title_with_warning(self, caplog):
        payload = {"jobs": [{"id_icims": "1"}, {"id_icims": "2", "title": "SDE"}]}
        with caplog.at_level("WARNING"):
            out = _parse_search_response(payload)
        assert len(out["jobs"]) == 1
        assert out["skipped_missing_title"] == 1
        assert "missing title" in caplog.text

    def test_warns_once_per_page_not_per_row(self, caplog):
        payload = {"jobs": [{"title": "a"}, {"title": "b"}, {"title": "c"}]}
        with caplog.at_level("WARNING"):
            _parse_search_response(payload)
        assert caplog.text.count("missing id_icims") == 1

    def test_non_int_hits_becomes_none(self):
        assert _parse_search_response({"jobs": [], "hits": "1303"})["hits"] is None

    def test_non_dict_payload_raises(self):
        with pytest.raises(JobSearchError):
            _parse_search_response(["not", "a", "dict"])

    def test_id_comes_from_id_icims_not_guid(self, amazon_raw_job):
        card = _parse_job_from_search(amazon_raw_job)
        assert card["id"] == "10496449"
        assert card["id"] != amazon_raw_job["id"]

    def test_card_carries_required_keys(self, amazon_raw_job):
        card = _parse_job_from_search(amazon_raw_job)
        # 'id' is mandatory — shared/incremental.py builds current_ids from it
        for key in ("id", "title", "job_url", "location", "posted_date", "description"):
            assert key in card
        assert card["job_url"].startswith("https://www.amazon.jobs/en/jobs/")
        assert card["posted_date"] == "2026-08-08"

    def test_team_label_flattened(self, amazon_raw_job):
        assert _parse_job_from_search(amazon_raw_job)["team"] == "team-aws-sdm"

    def test_team_non_dict_is_tolerated(self, amazon_raw_job):
        amazon_raw_job["team"] = "not-a-dict"
        assert _parse_job_from_search(amazon_raw_job)["team"] is None


# --------------------------------------------------------- fetch_search_results

@pytest.mark.asyncio
class TestFetchSearchResults:
    async def test_success(self, amazon_search_response):
        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={"data": amazon_search_response, "sanitized": False}
        )
        out = await fetch_search_results(page, "software engineer", 0)
        assert len(out["jobs"]) == 2
        assert out["hits"] == 1303

    async def test_passes_url_headers_and_timeout_into_js(self, amazon_search_response):
        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={"data": amazon_search_response, "sanitized": False}
        )
        await fetch_search_results(page, "software engineer", 300)

        _, arg = page.evaluate.call_args[0]
        assert arg["headers"] == {"Accept": "application/json"}
        assert arg["timeoutMs"] == api_client._FETCH_BROWSER_TIMEOUT_MS
        assert "offset=300" in arg["url"]
        assert "base_query=software+engineer" in arg["url"]

    async def test_sanitised_flag_warns(self, amazon_search_response, caplog):
        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={"data": amazon_search_response, "sanitized": True}
        )
        with caplog.at_level("WARNING"):
            await fetch_search_results(page, "software engineer", 0)
        assert "control-character sanitising" in caplog.text

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
        page.evaluate = AsyncMock(side_effect=RuntimeError("HTTP 503"))
        with pytest.raises(JobSearchError) as exc:
            await fetch_search_results(page, "software engineer", 0)
        assert "503" in str(exc.value)
