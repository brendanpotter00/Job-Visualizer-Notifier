"""Unit tests for the Gem fetch + transform service."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from api.services.gem_client import (
    GEM_BASE_URL,
    SOURCE_ID,
    _normalize_employment_type,
    fetch_jobs,
    transform_to_job_listings,
)

pytestmark = pytest.mark.asyncio


# Two-job fixture modelled after the live Gem response shape (see
# https://api.gem.com/job_board/v0/<slug>/job_posts/). Both jobs are
# fully-populated so happy-path assertions cover every field; later
# tests build variants from these.
ONE_JOB_RAW: dict[str, Any] = {
    "id": "4123456",
    "title": "Senior Software Engineer",
    "absolute_url": "https://jobs.gem.com/retool/4123456",
    "content": "<p>Build the future of internal tools.</p>",
    "content_plain": "Build the future of internal tools.",
    "created_at": "2026-01-10T08:00:00Z",
    "updated_at": "2026-01-12T10:00:00Z",
    "first_published_at": "2026-01-15T14:30:00-05:00",
    "employment_type": "full_time",
    "location_type": "remote",
    "location": {"name": "San Francisco, CA"},
    "departments": [{"id": "d1", "name": "Engineering"}],
    "offices": [
        {"id": "o1", "name": "San Francisco"},
        {"id": "o2", "name": "New York"},
    ],
    "internal_job_id": "JR-1001",
    "requisition_id": "R-1001",
}

TWO_JOB_FIXTURE: list[dict[str, Any]] = [
    ONE_JOB_RAW,
    {
        "id": "4987654",
        "title": "Product Designer",
        "absolute_url": "https://jobs.gem.com/retool/4987654",
        "content": "<p>Design role.</p>",
        "content_plain": "Design role.",
        "created_at": "2026-02-01T09:00:00Z",
        "updated_at": "2026-02-01T09:00:00Z",
        "first_published_at": "2026-03-01T09:00:00Z",
        "employment_type": "part_time",
        "location_type": "onsite",
        "location": None,
        "departments": [{"id": "d2", "name": "Design"}],
        "offices": [{"id": "o1", "name": "San Francisco"}],
        "internal_job_id": "JR-1002",
        "requisition_id": "R-1002",
    },
]

EMPTY_FIXTURE: list[Any] = []


def _client_with_handler(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


class TestFetchJobs:
    async def test_happy_path_returns_jobs_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/job_board/v0/retool/job_posts/"
            return httpx.Response(200, json=[ONE_JOB_RAW])

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("retool", client)

        assert isinstance(jobs, list)
        assert len(jobs) == 1
        assert jobs[0]["id"] == "4123456"

    async def test_empty_jobs_list_returns_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("retool", client)

        assert jobs == []

    async def test_non_2xx_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("retool", client)

    async def test_404_raises_http_status_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("nonexistent", client)

    async def test_non_list_payload_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # Gem returns a flat array; an envelope object is a clean
            # schema break — surface it as ValueError so the task layer
            # treats it as a failed run (and Procrastinate retries).
            return httpx.Response(200, json={"jobs": []})

        async with _client_with_handler(handler) as client:
            with pytest.raises(ValueError, match="not a list"):
                await fetch_jobs("retool", client)

    async def test_url_construction_uses_board_token(self):
        captured_url: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_url["value"] = str(request.url)
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            await fetch_jobs("nominal", client)

        assert captured_url["value"].startswith(f"{GEM_BASE_URL}/nominal/job_posts/")


class TestNormalizeEmploymentType:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("full_time", "Full-time"),
            ("part_time", "Part-time"),
            ("contract", "Contract"),
            ("intern", "Internship"),
            ("temporary", "Temporary"),
        ],
    )
    def test_known_mappings(self, raw: str, expected: str):
        assert _normalize_employment_type(raw) == expected

    def test_none_returns_none(self):
        assert _normalize_employment_type(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_employment_type("") is None

    def test_unknown_value_passes_through(self):
        # Schema drift visibility: we don't silently null unknown
        # values — we surface them verbatim for diagnosis.
        assert _normalize_employment_type("freelance") == "freelance"

    def test_non_string_coerced(self):
        assert _normalize_employment_type(42) == "42"


class TestTransformToJobListings:
    def test_empty_input_returns_empty_list(self):
        assert transform_to_job_listings("retool", []) == []

    def test_id_format(self):
        # Gem ids are observed numeric strings; the composite (source_id,
        # id) PK on job_listings is what enforces cross-source
        # uniqueness, so we store the raw upstream id directly.
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert len(result) == 1
        assert result[0].id == "4123456"

    def test_id_coerced_from_int(self):
        # Defensive: if Gem ever returns a numeric (not-yet-quoted) id,
        # we cast to str so the JobListing.id type contract holds.
        raw = dict(ONE_JOB_RAW)
        raw["id"] = 4123456
        result = transform_to_job_listings("retool", [raw])
        assert result[0].id == "4123456"

    def test_id_independent_of_company_id(self):
        # Same raw id transformed under a different company yields the
        # same job id (the PK distinguishes by source_id, not by
        # company). Composite (source_id='gem_api', id='4123456') is
        # what guarantees uniqueness even across companies in this
        # plan; Gem ids are unique within a board.
        result = transform_to_job_listings("nominal", [ONE_JOB_RAW])
        assert result[0].id == "4123456"

    def test_basic_fields_match_fixture(self):
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        job = result[0]
        assert job.title == "Senior Software Engineer"
        assert job.company == "retool"
        # First office.name preferred over location.name.
        assert job.location == "San Francisco"
        assert job.url == "https://jobs.gem.com/retool/4123456"
        assert job.source_id == SOURCE_ID
        assert job.status == "OPEN"
        assert job.consecutive_misses == 0
        assert job.closed_on is None
        assert job.has_matched is False

    def test_location_falls_back_to_location_name(self):
        # offices empty -> use location.name.
        raw = dict(ONE_JOB_RAW)
        raw["offices"] = []
        result = transform_to_job_listings("retool", [raw])
        assert result[0].location == "San Francisco, CA"

    def test_location_none_when_no_office_or_location(self):
        raw = dict(ONE_JOB_RAW)
        raw["offices"] = []
        raw["location"] = None
        result = transform_to_job_listings("retool", [raw])
        assert result[0].location is None

    def test_posted_on_parsed_to_utc(self):
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert result[0].posted_on is not None
        # "2026-01-15T14:30:00-05:00" -> "2026-01-15T19:30:00+00:00"
        assert result[0].posted_on.startswith("2026-01-15T19:30:00")
        assert result[0].posted_on.endswith("+00:00") or result[0].posted_on.endswith(
            "Z"
        )

    def test_posted_on_falls_back_to_created_at(self):
        # first_published_at can be null on brand-new postings; we
        # fall back to created_at so posted_on is never None for any
        # job that has either timestamp.
        raw = dict(ONE_JOB_RAW)
        raw["first_published_at"] = None
        result = transform_to_job_listings("retool", [raw])
        assert result[0].posted_on is not None
        assert result[0].posted_on.startswith("2026-01-10T08:00:00")

    def test_is_remote_eligible_truthy(self):
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert result[0].details["is_remote_eligible"] is True

    def test_is_remote_eligible_falsy_for_onsite(self):
        # "onsite" / "hybrid" / null / missing all map to False.
        raw_onsite = dict(ONE_JOB_RAW)
        raw_onsite["location_type"] = "onsite"
        raw_hybrid = dict(ONE_JOB_RAW)
        raw_hybrid["location_type"] = "hybrid"
        raw_null = dict(ONE_JOB_RAW)
        raw_null["location_type"] = None
        raw_missing = dict(ONE_JOB_RAW)
        raw_missing.pop("location_type", None)
        result = transform_to_job_listings(
            "retool", [raw_onsite, raw_hybrid, raw_null, raw_missing]
        )
        for job in result:
            assert job.details["is_remote_eligible"] is False

    def test_employment_type_normalized(self):
        result = transform_to_job_listings("retool", TWO_JOB_FIXTURE)
        assert result[0].details["employment_type"] == "Full-time"
        assert result[1].details["employment_type"] == "Part-time"

    def test_department_and_office_passthrough(self):
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert result[0].details["department"] == "Engineering"
        assert result[0].details["office"] == "San Francisco"

    def test_secondary_offices_filtered(self):
        # offices[1:] with at least one valid entry yields the names.
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert result[0].details["secondary_offices"] == ["New York"]

    def test_secondary_offices_empty_when_only_one_office(self):
        result = transform_to_job_listings("retool", [TWO_JOB_FIXTURE[1]])
        # offices has one entry, so secondary_offices is empty.
        assert result[0].details["secondary_offices"] == []

    def test_secondary_offices_filters_malformed_entries(self):
        # Defensive: mix valid dicts, dicts missing 'name', a non-dict.
        raw = dict(ONE_JOB_RAW)
        raw["offices"] = [
            {"id": "o1", "name": "San Francisco"},
            {"id": "o2", "name": "New York"},
            {"id": "o3"},  # no name
            {"id": "o4", "name": ""},  # empty name filtered
            "not-a-dict",
            {"id": "o5", "name": "London"},
        ]
        result = transform_to_job_listings("retool", [raw])
        assert result[0].details["secondary_offices"] == ["New York", "London"]

    def test_details_always_has_experience_level_none(self):
        result = transform_to_job_listings("retool", TWO_JOB_FIXTURE)
        for job in result:
            assert "experience_level" in job.details
            assert job.details["experience_level"] is None

    def test_content_html_preserved(self):
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert (
            result[0].details["content_html"]
            == "<p>Build the future of internal tools.</p>"
        )

    def test_published_at_preserved_in_details(self):
        # Raw source value, not normalized — normalization lives on
        # ``posted_on`` only.
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        assert result[0].details["published_at"] == "2026-01-15T14:30:00-05:00"

    def test_unparseable_posted_on_logged_and_nulled(self, caplog):
        # Per feedback_correctness_over_dont_crash: a malformed
        # timestamp must surface as a clean missing value, NOT silently
        # passed through. Row preserved (no crash). The log lands at
        # ERROR level so Railway's @level:error filter surfaces the
        # data-quality issue.
        import logging

        raw = dict(ONE_JOB_RAW)
        raw["first_published_at"] = "not-a-real-date"
        raw["created_at"] = None
        with caplog.at_level(logging.ERROR, logger="api.services.gem_client"):
            result = transform_to_job_listings("retool", [raw])
        assert result[0].posted_on is None
        matching = [
            rec
            for rec in caplog.records
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

    def test_missing_posted_on_yields_none_without_log(self, caplog):
        # When both first_published_at and created_at are absent, posted_on
        # is None and no ERROR is logged (nothing to parse).
        import logging

        raw = dict(ONE_JOB_RAW)
        raw["first_published_at"] = None
        raw["created_at"] = None
        with caplog.at_level(logging.ERROR, logger="api.services.gem_client"):
            result = transform_to_job_listings("retool", [raw])
        assert result[0].posted_on is None
        assert not [
            rec
            for rec in caplog.records
            if "unparseable posted_on" in rec.getMessage()
        ]

    def test_details_roundtrips_as_json(self):
        result = transform_to_job_listings("retool", TWO_JOB_FIXTURE)
        for job in result:
            json.dumps(job.details)

    def test_missing_id_raises(self):
        bad = {"title": "x", "absolute_url": "y"}
        with pytest.raises(ValueError, match="missing 'id'"):
            transform_to_job_listings("retool", [bad])

    def test_first_and_last_seen_set_to_same_iso_string(self):
        result = transform_to_job_listings("retool", [ONE_JOB_RAW])
        job = result[0]
        assert job.first_seen_at == job.last_seen_at == job.created_at
        assert job.created_at.endswith("Z")
