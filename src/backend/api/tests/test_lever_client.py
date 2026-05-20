"""Unit tests for the Lever fetch + transform service."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from api.services.lever_client import (
    LEVER_BASE_URL,
    SOURCE_ID,
    fetch_jobs,
    transform_to_job_listings,
)

pytestmark = pytest.mark.asyncio


ONE_JOB_FIXTURE: list[dict[str, Any]] = [
    {
        "id": "9b56dc97-04a5-4c84-bc73-19f7d7f43cce",
        "text": "Senior Software Engineer",
        "hostedUrl": "https://jobs.lever.co/palantir/9b56dc97",
        "categories": {
            "commitment": "Full-time",
            "department": "Engineering",
            "location": "Palo Alto",
            "team": "Platform",
        },
        "createdAt": 1714857600000,
        "tags": ["python", ["typescript", "react"], None, "", "rust"],
        "workplaceType": "remote",
        "description": "<p>Build software at Palantir.</p>",
        "descriptionPlain": "Build software at Palantir.",
    }
]

TWO_JOB_FIXTURE: list[dict[str, Any]] = [
    ONE_JOB_FIXTURE[0],
    {
        "id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
        "text": "Product Designer",
        "hostedUrl": "https://jobs.lever.co/spotify/b2c3d4e5",
        "categories": {
            "commitment": "Full-time",
            "department": "Design",
            "location": "Remote",
        },
        "createdAt": 1715000000000,
        "tags": [],
        "workplaceType": "unspecified",
        "descriptionPlain": "Design role.",
    },
]

EMPTY_FIXTURE: list[dict[str, Any]] = []


def _client_with_handler(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


class TestFetchJobs:
    async def test_happy_path_returns_jobs_list(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v0/postings/palantir"
            assert request.url.params["mode"] == "json"
            return httpx.Response(200, json=ONE_JOB_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("palantir", client)

        assert isinstance(jobs, list)
        assert len(jobs) == 1
        assert jobs[0]["id"] == "9b56dc97-04a5-4c84-bc73-19f7d7f43cce"

    async def test_empty_list_returns_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            jobs = await fetch_jobs("palantir", client)

        assert jobs == []

    async def test_non_2xx_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        async with _client_with_handler(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs("palantir", client)

    async def test_non_list_root_raises_value_error(self):
        """Lever's contract is a top-level array. A wrapping object means
        the upstream schema shifted — fail loudly rather than silently
        interpreting nothing as 'no jobs' and triggering the safety guard
        for the wrong reason."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"postings": []})

        async with _client_with_handler(handler) as client:
            with pytest.raises(ValueError, match="not a list"):
                await fetch_jobs("palantir", client)

    async def test_uses_default_base_url(self):
        """Smoke: requests go to api.lever.co, not somewhere else."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json=EMPTY_FIXTURE)

        async with _client_with_handler(handler) as client:
            await fetch_jobs("palantir", client)

        assert captured["url"].startswith(LEVER_BASE_URL)


class TestTransformToJobListings:
    def test_happy_path_one_job(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert len(listings) == 1
        listing = listings[0]

        assert listing.id == "9b56dc97-04a5-4c84-bc73-19f7d7f43cce"
        assert listing.source_id == SOURCE_ID == "lever_api"
        assert listing.company == "palantir"
        assert listing.title == "Senior Software Engineer"
        assert listing.url == "https://jobs.lever.co/palantir/9b56dc97"
        assert listing.location == "Palo Alto"
        assert listing.status == "OPEN"
        assert listing.consecutive_misses == 0
        assert listing.details_scraped is True

    def test_id_is_string_even_if_int(self):
        """Lever ids are observed UUID-strings, but cast defensively."""
        raw = {**ONE_JOB_FIXTURE[0], "id": 12345}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].id == "12345"

    def test_posted_on_normalized_to_utc(self):
        """createdAt 1714857600000 ms == 2024-05-04T21:20:00+00:00 UTC."""
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert listings[0].posted_on == "2024-05-04T21:20:00+00:00"

    def test_is_remote_eligible_truthy_when_workplace_type_remote(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert listings[0].details["is_remote_eligible"] is True

    def test_is_remote_eligible_falsy_when_workplace_type_onsite(self):
        raw = {**ONE_JOB_FIXTURE[0], "workplaceType": "onsite"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["is_remote_eligible"] is False

    def test_is_remote_eligible_falsy_when_workplace_type_unspecified(self):
        raw = {**ONE_JOB_FIXTURE[0], "workplaceType": "unspecified"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["is_remote_eligible"] is False

    def test_is_remote_eligible_falsy_when_workplace_type_missing(self):
        raw = {k: v for k, v in ONE_JOB_FIXTURE[0].items() if k != "workplaceType"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["is_remote_eligible"] is False

    def test_all_details_keys_present(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        details = listings[0].details
        expected_keys = {
            "department",
            "team",
            "secondary_locations",
            "employment_type",
            "is_remote_eligible",
            "compensation_summary",
            "published_at",
            "description_html",
            "experience_level",
            "tags",
        }
        assert set(details.keys()) == expected_keys

    def test_experience_level_always_none(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert listings[0].details["experience_level"] is None

    def test_description_falls_back_to_descriptionPlain(self):
        raw = {k: v for k, v in ONE_JOB_FIXTURE[0].items() if k != "description"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["description_html"] == "Build software at Palantir."

    def test_description_prefers_html_over_plain(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        # ONE_JOB_FIXTURE has both fields; the HTML version wins.
        assert listings[0].details["description_html"] == "<p>Build software at Palantir.</p>"

    def test_description_html_none_when_both_missing(self):
        raw = {
            k: v
            for k, v in ONE_JOB_FIXTURE[0].items()
            if k not in ("description", "descriptionPlain")
        }
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["description_html"] is None

    def test_secondary_locations_always_empty_list(self):
        """Lever postings endpoint doesn't expose secondary locations —
        the field stays an empty list so the JSONB shape stays parallel
        to Ashby/Greenhouse."""
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert listings[0].details["secondary_locations"] == []

    def test_compensation_summary_always_none(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert listings[0].details["compensation_summary"] is None

    def test_categories_object_missing_treated_as_empty_dict(self):
        raw = {k: v for k, v in ONE_JOB_FIXTURE[0].items() if k != "categories"}
        listings = transform_to_job_listings("palantir", [raw])
        details = listings[0].details
        assert details["department"] is None
        assert details["team"] is None
        assert details["employment_type"] is None
        assert listings[0].location is None

    def test_categories_non_dict_coerced_to_empty(self):
        """A schema drift where categories becomes a list/string must not
        crash the whole batch; treat as empty and log nothing (the row is
        still valid)."""
        raw = {**ONE_JOB_FIXTURE[0], "categories": ["unexpected"]}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["department"] is None
        assert listings[0].location is None

    def test_two_jobs_both_transform(self):
        listings = transform_to_job_listings("palantir", TWO_JOB_FIXTURE)
        assert len(listings) == 2
        assert listings[0].id == "9b56dc97-04a5-4c84-bc73-19f7d7f43cce"
        assert listings[1].id == "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e"

    def test_first_and_last_seen_set_to_same_iso_string(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        assert listings[0].first_seen_at == listings[0].last_seen_at

    def test_missing_id_raises(self):
        raw = {k: v for k, v in ONE_JOB_FIXTURE[0].items() if k != "id"}
        with pytest.raises(ValueError, match="missing 'id'"):
            transform_to_job_listings("palantir", [raw])

    def test_unparseable_createdAt_stored_as_none(self):
        """Garbage createdAt must not crash; posted_on goes to None and
        details.published_at to None. The row itself is preserved."""
        raw = {**ONE_JOB_FIXTURE[0], "createdAt": "not-a-number"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].posted_on is None
        assert listings[0].details["published_at"] is None

    def test_missing_createdAt_stored_as_none(self):
        raw = {k: v for k, v in ONE_JOB_FIXTURE[0].items() if k != "createdAt"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].posted_on is None
        assert listings[0].details["published_at"] is None


class TestSanitizeTags:
    """Mirror the frontend ``sanitizeTags`` semantics from
    ``src/frontend/src/lib/tags.ts``."""

    def test_flattens_nested_arrays(self):
        listings = transform_to_job_listings("palantir", ONE_JOB_FIXTURE)
        # Fixture: ["python", ["typescript", "react"], None, "", "rust"]
        # Expected: ["python", "typescript", "react", "rust"]
        assert listings[0].details["tags"] == ["python", "typescript", "react", "rust"]

    def test_empty_tags_yields_empty_list(self):
        raw = {**ONE_JOB_FIXTURE[0], "tags": []}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["tags"] == []

    def test_missing_tags_yields_empty_list(self):
        raw = {k: v for k, v in ONE_JOB_FIXTURE[0].items() if k != "tags"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["tags"] == []

    def test_non_list_tags_yields_empty_list(self):
        raw = {**ONE_JOB_FIXTURE[0], "tags": "not-a-list"}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["tags"] == []

    def test_drops_non_string_entries(self):
        """Frontend sanitizeTags drops numbers / objects / bools."""
        raw = {**ONE_JOB_FIXTURE[0], "tags": ["a", 1, True, {"k": "v"}, "b"]}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["tags"] == ["a", "b"]

    def test_preserves_insertion_order(self):
        raw = {**ONE_JOB_FIXTURE[0], "tags": ["z", "a", "m", "b"]}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["tags"] == ["z", "a", "m", "b"]

    def test_preserves_duplicates(self):
        """Mirror frontend behaviour exactly — sanitizeTags does NOT
        deduplicate, so neither does the backend."""
        raw = {**ONE_JOB_FIXTURE[0], "tags": ["python", "python", "rust"]}
        listings = transform_to_job_listings("palantir", [raw])
        assert listings[0].details["tags"] == ["python", "python", "rust"]


class TestMsToIso8601:
    """Direct tests on the epoch-ms -> ISO 8601 helper."""

    def test_epoch_zero(self):
        from api.services.lever_client import _ms_to_iso8601
        assert _ms_to_iso8601(0) == "1970-01-01T00:00:00+00:00"

    def test_none_returns_none(self):
        from api.services.lever_client import _ms_to_iso8601
        assert _ms_to_iso8601(None) is None

    def test_string_returns_none(self):
        from api.services.lever_client import _ms_to_iso8601
        assert _ms_to_iso8601("12345") is None

    def test_bool_returns_none(self):
        """Python: bool is subclass of int. Reject explicitly so
        True/False don't silently become 1970-01-01T00:00:00.001 / epoch 0."""
        from api.services.lever_client import _ms_to_iso8601
        assert _ms_to_iso8601(True) is None
        assert _ms_to_iso8601(False) is None

    def test_known_value(self):
        from api.services.lever_client import _ms_to_iso8601
        # 1714857600000 ms = 2024-05-04T21:20:00+00:00 UTC.
        assert _ms_to_iso8601(1714857600000) == "2024-05-04T21:20:00+00:00"

    def test_float_accepted(self):
        from api.services.lever_client import _ms_to_iso8601
        assert _ms_to_iso8601(1714857600000.0) == "2024-05-04T21:20:00+00:00"

    def test_overflow_returns_none(self):
        from api.services.lever_client import _ms_to_iso8601
        # Year ~+292,000 — well outside Python datetime.MAX (year 9999).
        # OverflowError gets caught and we return None instead of crashing.
        assert _ms_to_iso8601(10**18) is None
