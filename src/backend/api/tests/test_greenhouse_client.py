"""Unit tests for the Greenhouse fetch + transform service."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from api.services.greenhouse_client import (
    GREENHOUSE_BASE_URL,
    SOURCE_ID,
    fetch_jobs,
    transform_to_job_listings,
)

pytestmark = pytest.mark.asyncio


ONE_JOB_FIXTURE: dict[str, Any] = {
    "jobs": [
        {
            "id": 7546284,
            "title": "Account Executive, AI Sales",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=7546284",
            "location": {"name": "San Francisco, CA"},
            "departments": [{"id": 1, "name": "Sales"}],
            "offices": [
                {"id": 100, "name": "San Francisco HQ", "location": "San Francisco, CA"}
            ],
            "updated_at": "2026-05-14T13:08:51-04:00",
            "first_published": "2026-02-13T12:39:30-05:00",
            "metadata": [
                {"id": 1, "name": "Team", "value": "GTM"},
                {"id": 2, "name": "Stack", "value": ["Python", "TypeScript"]},
                {"id": 3, "name": "Empty", "value": None},
            ],
            "content": "<h2>Who we are</h2><p>Stripe builds...</p>",
        }
    ]
}

TWO_JOB_FIXTURE: dict[str, Any] = {
    "jobs": [
        ONE_JOB_FIXTURE["jobs"][0],
        {
            "id": 9999001,
            "title": "Software Engineer",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=9999001",
            "location": {"name": "Remote"},
            "departments": [],
            "offices": [],
            "updated_at": "2026-05-10T10:00:00Z",
            "first_published": None,
            "metadata": None,
            "content": "<p>Engineering role</p>",
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
            assert request.url.path == "/v1/boards/stripe/jobs"
            assert request.url.params["content"] == "true"
            return httpx.Response(200, json=ONE_JOB_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("stripe", client)

        assert isinstance(jobs, list)
        assert len(jobs) == 1
        assert jobs[0]["id"] == 7546284

    async def test_empty_response_returns_empty_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("stripe", client)

        assert jobs == []

    async def test_5xx_raises_http_status_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "service unavailable"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("stripe", client)

    async def test_404_raises_http_status_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("nonexistent-board", client)

    async def test_malformed_response_missing_jobs_key_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(ValueError, match="missing 'jobs' key"):
                await fetch_jobs("stripe", client)

    async def test_malformed_response_jobs_not_list_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": {"oops": "dict"}})

        async with _client_with_handler(handler) as client:
            with pytest.raises(ValueError, match="not a list"):
                await fetch_jobs("stripe", client)

    async def test_url_construction_uses_board_token(self):
        captured_url: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_url["value"] = str(request.url)
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            await fetch_jobs("airbnb", client)

        assert captured_url["value"].startswith(
            f"{GREENHOUSE_BASE_URL}/airbnb/jobs"
        )
        assert "content=true" in captured_url["value"]


class TestTransformToJobListings:
    def test_empty_input_returns_empty_list(self):
        assert transform_to_job_listings("stripe", "stripe", []) == []

    def test_id_format_uses_board_token(self):
        # Use distinct values so the assertion actually proves the id is
        # built from board_token (not company_id). Previously both were
        # "spacex", which made the test pass even if the wrong field was
        # used to build the id.
        result = transform_to_job_listings(
            company_id="spacex",
            board_token="rocket",
            raw_jobs=ONE_JOB_FIXTURE["jobs"],
        )
        assert len(result) == 1
        assert result[0].id == "greenhouse_rocket_7546284"

    def test_id_format_with_distinct_board_token(self):
        result = transform_to_job_listings(
            company_id="xai",
            board_token="x",
            raw_jobs=ONE_JOB_FIXTURE["jobs"],
        )
        assert result[0].id == "greenhouse_x_7546284"

    def test_basic_fields_match_fixture(self):
        result = transform_to_job_listings("stripe", "stripe", ONE_JOB_FIXTURE["jobs"])
        job = result[0]
        assert job.title == "Account Executive, AI Sales"
        assert job.company == "stripe"
        assert job.location == "San Francisco HQ"
        assert job.url == "https://stripe.com/jobs/search?gh_jid=7546284"
        assert job.source_id == SOURCE_ID
        assert job.status == "OPEN"
        assert job.consecutive_misses == 0
        assert job.closed_on is None
        assert job.has_matched is False

    def test_location_fallback_when_no_office(self):
        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw["offices"] = []
        result = transform_to_job_listings("stripe", "stripe", [raw])
        assert result[0].location == "San Francisco, CA"

    def test_location_none_when_neither_present(self):
        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw["offices"] = []
        raw["location"] = None
        result = transform_to_job_listings("stripe", "stripe", [raw])
        assert result[0].location is None

    def test_no_departments_does_not_raise(self):
        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw["departments"] = []
        result = transform_to_job_listings("stripe", "stripe", [raw])
        assert result[0].details["department"] is None

    def test_posted_on_parsed_to_utc(self):
        result = transform_to_job_listings("stripe", "stripe", ONE_JOB_FIXTURE["jobs"])
        assert result[0].posted_on is not None
        assert result[0].posted_on.startswith("2026-02-13T17:39:30")
        assert result[0].posted_on.endswith("+00:00")

    def test_posted_on_falls_back_to_updated_at(self):
        result = transform_to_job_listings("stripe", "stripe", TWO_JOB_FIXTURE["jobs"])
        assert result[1].posted_on is not None
        assert result[1].posted_on.startswith("2026-05-10T10:00:00")
        assert result[1].posted_on.endswith("+00:00")

    def test_posted_on_unparseable_becomes_none(self, caplog):
        # Per feedback_correctness_over_dont_crash: a malformed timestamp
        # must surface as a clean missing value, NOT silently passed through
        # as a corrupt string. Row is preserved (no crash), with a warning.
        import logging

        raw = dict(ONE_JOB_FIXTURE["jobs"][0])
        raw["first_published"] = "not-a-real-date"
        raw["updated_at"] = "also-bogus"
        with caplog.at_level(logging.WARNING, logger="api.services.greenhouse_client"):
            result = transform_to_job_listings("stripe", "stripe", [raw])
        assert result[0].posted_on is None
        assert any(
            "unparseable posted_on" in rec.getMessage() for rec in caplog.records
        ), f"expected unparseable warning, got: {[r.getMessage() for r in caplog.records]}"

    def test_details_jsonb_has_field_tolerant_keys(self):
        result = transform_to_job_listings("stripe", "stripe", ONE_JOB_FIXTURE["jobs"])
        details = result[0].details
        assert "experience_level" in details
        assert "is_remote_eligible" in details
        assert details["experience_level"] is None
        assert details["is_remote_eligible"] is False
        assert details["department"] == "Sales"
        assert details["office_locations"] == ["San Francisco HQ"]
        assert details["tags"] == ["GTM", "Python", "TypeScript"]
        assert details["absolute_url"].startswith("https://stripe.com")
        assert "content" in details

    def test_details_roundtrips_as_json(self):
        result = transform_to_job_listings("stripe", "stripe", TWO_JOB_FIXTURE["jobs"])
        for job in result:
            json.dumps(job.details)

    def test_metadata_none_results_in_empty_tags(self):
        result = transform_to_job_listings("stripe", "stripe", TWO_JOB_FIXTURE["jobs"])
        assert result[1].details["tags"] == []

    def test_raw_id_missing_raises(self):
        bad = {"title": "x", "absolute_url": "y"}
        with pytest.raises(ValueError, match="missing 'id'"):
            transform_to_job_listings("stripe", "stripe", [bad])

    def test_first_and_last_seen_set_to_same_iso_string(self):
        result = transform_to_job_listings("stripe", "stripe", ONE_JOB_FIXTURE["jobs"])
        job = result[0]
        assert job.first_seen_at == job.last_seen_at == job.created_at
        assert job.created_at.endswith("Z")
