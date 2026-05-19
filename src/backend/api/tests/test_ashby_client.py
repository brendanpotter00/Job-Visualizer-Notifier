"""Unit tests for the Ashby fetch + transform service."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from api.services.ashby_client import (
    ASHBY_BASE_URL,
    SOURCE_ID,
    fetch_jobs,
    transform_to_job_listings,
)

pytestmark = pytest.mark.asyncio


ONE_JOB_FIXTURE: dict[str, Any] = {
    "jobs": [
        {
            "id": "uuid-1",
            "title": "Senior Software Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/notion/uuid-1",
            "location": "San Francisco, CA",
            "department": "Engineering",
            "team": "Platform",
            "employmentType": "FullTime",
            "isRemote": True,
            "publishedAt": "2026-01-15T14:30:00-05:00",
            "secondaryLocations": [
                {"location": "New York, NY"},
                {"location": "Remote (US)"},
            ],
            "compensation": {
                "compensationTierSummary": "$180K - $240K + equity",
            },
            "descriptionHtml": "<p>Join Notion to build the future of work.</p>",
        }
    ],
    "jobBoardTitle": "Notion",
}

TWO_JOB_FIXTURE: dict[str, Any] = {
    "jobs": [
        ONE_JOB_FIXTURE["jobs"][0],
        {
            "id": "uuid-2",
            "title": "Product Designer",
            "jobUrl": "https://jobs.ashbyhq.com/notion/uuid-2",
            "location": "Remote",
            "department": "Design",
            "team": None,
            "employmentType": "FullTime",
            "isRemote": False,
            "publishedAt": "2026-03-01T09:00:00Z",
            "secondaryLocations": [],
            "compensation": None,
            "descriptionHtml": "<p>Design role.</p>",
        },
    ]
}

EMPTY_FIXTURE: dict[str, Any] = {"jobs": []}


def _client_with_handler(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


class TestFetchJobs:
    async def test_happy_path_returns_jobs_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/posting-api/job-board/notion"
            assert request.url.params["includeCompensation"] == "true"
            return httpx.Response(200, json=ONE_JOB_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("notion", client)

        assert isinstance(jobs, list)
        assert len(jobs) == 1
        assert jobs[0]["id"] == "uuid-1"

    async def test_empty_jobs_list_returns_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("notion", client)

        assert jobs == []

    async def test_non_2xx_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("notion", client)

    async def test_404_raises_http_status_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("nonexistent-board", client)

    async def test_missing_jobs_key_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"other": "thing"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(ValueError, match="missing 'jobs' key"):
                await fetch_jobs("notion", client)

    async def test_non_list_jobs_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": "not a list"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(ValueError, match="not a list"):
                await fetch_jobs("notion", client)

    async def test_url_construction_uses_board_token(self):
        captured_url: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_url["value"] = str(request.url)
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            await fetch_jobs("openai", client)

        assert captured_url["value"].startswith(f"{ASHBY_BASE_URL}/openai")
        assert "includeCompensation=true" in captured_url["value"]


class TestTransformToJobListings:
    def test_empty_input_returns_empty_list(self):
        assert transform_to_job_listings("notion", []) == []

    def test_id_format(self):
        # Ashby raw IDs are UUID strings, globally unique across the Ashby
        # platform. The composite (source_id, id) PK on job_listings enforces
        # cross-source uniqueness in the schema, so we store raw upstream ids
        # directly.
        result = transform_to_job_listings(
            company_id="notion",
            raw_jobs=ONE_JOB_FIXTURE["jobs"],
        )
        assert len(result) == 1
        assert result[0].id == "uuid-1"

    def test_id_independent_of_company_id(self):
        result = transform_to_job_listings(
            company_id="ramp",
            raw_jobs=ONE_JOB_FIXTURE["jobs"],
        )
        assert result[0].id == "uuid-1"

    def test_basic_fields_match_fixture(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        job = result[0]
        assert job.title == "Senior Software Engineer"
        assert job.company == "notion"
        assert job.location == "San Francisco, CA"
        assert job.url == "https://jobs.ashbyhq.com/notion/uuid-1"
        assert job.source_id == SOURCE_ID
        assert job.status == "OPEN"
        assert job.consecutive_misses == 0
        assert job.closed_on is None
        assert job.has_matched is False

    def test_posted_on_parsed_to_utc(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        assert result[0].posted_on is not None
        # "2026-01-15T14:30:00-05:00" -> "2026-01-15T19:30:00+00:00"
        assert result[0].posted_on.startswith("2026-01-15T19:30:00")
        assert result[0].posted_on.endswith("+00:00") or result[0].posted_on.endswith(
            "Z"
        )

    def test_is_remote_eligible_truthy(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        assert result[0].details["is_remote_eligible"] is True

    def test_is_remote_eligible_falsy(self):
        # Explicit false on one row, key-missing on another -> both False.
        raw_false = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw_false["isRemote"] = False
        raw_missing = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw_missing.pop("isRemote", None)
        result = transform_to_job_listings("notion", [raw_false, raw_missing])
        assert result[0].details["is_remote_eligible"] is False
        assert result[1].details["is_remote_eligible"] is False

    def test_compensation_summary_extracted(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        assert result[0].details["compensation_summary"] == "$180K - $240K + equity"

    def test_compensation_summary_absent(self):
        # compensation=None (one common shape) and key-missing both yield None.
        raw_null = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw_null["compensation"] = None
        raw_missing = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw_missing.pop("compensation", None)
        result = transform_to_job_listings("notion", [raw_null, raw_missing])
        assert result[0].details["compensation_summary"] is None
        assert result[1].details["compensation_summary"] is None

    def test_secondary_locations_filtered(self):
        # Mix of valid dicts, dicts with no ``location`` key, and a non-dict
        # garbage entry. Only the non-empty string locations survive.
        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw["secondaryLocations"] = [
            {"location": "New York, NY"},
            {"location": ""},  # empty string filtered out
            {"id": "no-location-key"},  # missing key
            "not-a-dict",  # non-dict
            None,  # None
            {"location": "London, UK"},
        ]
        result = transform_to_job_listings("notion", [raw])
        assert result[0].details["secondary_locations"] == [
            "New York, NY",
            "London, UK",
        ]

    def test_secondary_locations_missing_is_empty_list(self):
        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw.pop("secondaryLocations", None)
        result = transform_to_job_listings("notion", [raw])
        assert result[0].details["secondary_locations"] == []

    def test_employment_type_passthrough(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        assert result[0].details["employment_type"] == "FullTime"

    def test_details_always_has_experience_level_none(self):
        result = transform_to_job_listings("notion", TWO_JOB_FIXTURE["jobs"])
        for job in result:
            assert "experience_level" in job.details
            assert job.details["experience_level"] is None

    def test_description_html_preserved(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        assert (
            result[0].details["description_html"]
            == "<p>Join Notion to build the future of work.</p>"
        )

    def test_department_and_team_passthrough(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        assert result[0].details["department"] == "Engineering"
        assert result[0].details["team"] == "Platform"

    def test_published_at_preserved_in_details(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        # Raw source value, not normalized — normalization lives on
        # ``posted_on`` only.
        assert result[0].details["published_at"] == "2026-01-15T14:30:00-05:00"

    def test_unparseable_published_at_logged_and_nulled(self, caplog):
        # Per feedback_correctness_over_dont_crash: a malformed timestamp
        # must surface as a clean missing value, NOT silently passed through
        # as a corrupt string. Row is preserved (no crash). The log lands
        # at ERROR level so Railway's @level:error filter surfaces the
        # data-quality issue.
        import logging

        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw["publishedAt"] = "not-a-real-date"
        with caplog.at_level(logging.ERROR, logger="api.services.ashby_client"):
            result = transform_to_job_listings("notion", [raw])
        assert result[0].posted_on is None
        matching = [
            rec for rec in caplog.records
            if "unparseable posted_on" in rec.getMessage()
        ]
        assert matching, (
            f"expected unparseable posted_on log, got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )
        assert matching[0].levelname == "ERROR", (
            f"expected ERROR level for data-quality issue, got "
            f"{matching[0].levelname}"
        )
        assert "data quality issue" in matching[0].getMessage(), (
            "log message must contain 'data quality issue' for grep-ability"
        )

    def test_missing_published_at_yields_none_without_log(self, caplog):
        # When the source field is absent entirely, posted_on is None and
        # no ERROR is logged (it's not a data quality issue — just nothing
        # to parse).
        import logging

        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw.pop("publishedAt", None)
        with caplog.at_level(logging.ERROR, logger="api.services.ashby_client"):
            result = transform_to_job_listings("notion", [raw])
        assert result[0].posted_on is None
        assert not [
            rec for rec in caplog.records
            if "unparseable posted_on" in rec.getMessage()
        ]

    def test_details_roundtrips_as_json(self):
        result = transform_to_job_listings("notion", TWO_JOB_FIXTURE["jobs"])
        for job in result:
            json.dumps(job.details)

    def test_missing_id_raises(self):
        bad = {"title": "x", "jobUrl": "y"}
        with pytest.raises(ValueError, match="missing 'id'"):
            transform_to_job_listings("notion", [bad])

    def test_first_and_last_seen_set_to_same_iso_string(self):
        result = transform_to_job_listings("notion", ONE_JOB_FIXTURE["jobs"])
        job = result[0]
        assert job.first_seen_at == job.last_seen_at == job.created_at
        assert job.created_at.endswith("Z")
