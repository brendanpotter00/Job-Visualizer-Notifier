"""Unit tests for the Workday fetch + transform service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from api.services.workday_client import (
    SOURCE_ID,
    WORKDAY_MAX_PAGES,
    WORKDAY_PAGE_SIZE,
    _parse_workday_date,
    _validate_provider_config,
    fetch_jobs,
    transform_to_job_listings,
)

pytestmark = pytest.mark.asyncio


PROVIDER_CONFIG_NVIDIA: dict[str, Any] = {
    "base_url": "https://nvidia.wd5.myworkdayjobs.com",
    "tenant_slug": "nvidia",
    "career_site_slug": "NVIDIAExternalCareerSite",
    "default_facets": {
        "locationHierarchy1": ["2fcb99c455831013ea52fb338f2932d8"],
    },
}

PROVIDER_CONFIG_SLACK: dict[str, Any] = {
    "base_url": "https://salesforce.wd12.myworkdayjobs.com",
    "tenant_slug": "salesforce",
    "career_site_slug": "Slack",
}


def _job(idx: int, **overrides: Any) -> dict[str, Any]:
    base = {
        "title": f"Software Engineer {idx}",
        "externalPath": f"/job/US-CA-Santa-Clara/Software-Engineer-{idx}_JR{idx:04d}",
        "locationsText": "Santa Clara, CA",
        "postedOn": "Posted Today",
        "bulletFields": [f"JR{idx:04d}"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# fetch_jobs — POST + pagination
# ---------------------------------------------------------------------------

class TestFetchJobsPagination:
    async def test_single_page_under_limit_returns_all_jobs(self) -> None:
        """Total = 5, all returned in one page → no second call."""
        call_count = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            body = req.read()
            # POST body must contain limit/offset/searchText/appliedFacets.
            import json
            parsed = json.loads(body)
            assert parsed["limit"] == WORKDAY_PAGE_SIZE
            assert parsed["offset"] == 0
            assert parsed["searchText"] == ""
            assert parsed["appliedFacets"] == PROVIDER_CONFIG_NVIDIA["default_facets"]
            jobs = [_job(i) for i in range(5)]
            return httpx.Response(200, json={"total": 5, "jobPostings": jobs})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

        assert len(result) == 5
        assert call_count["n"] == 1

    async def test_multi_page_paginates_until_total_reached(self) -> None:
        """Total = 25 in pages of 20 → two calls (offset 0, then 20)."""
        offsets_seen: list[int] = []

        def handler(req: httpx.Request) -> httpx.Response:
            import json
            parsed = json.loads(req.read())
            offset = parsed["offset"]
            offsets_seen.append(offset)
            if offset == 0:
                jobs = [_job(i) for i in range(20)]
            elif offset == 20:
                jobs = [_job(20 + i) for i in range(5)]
            else:
                pytest.fail(f"unexpected offset {offset}")
            return httpx.Response(200, json={"total": 25, "jobPostings": jobs})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

        assert len(result) == 25
        assert offsets_seen == [0, 20]

    async def test_empty_first_page_stops_immediately(self) -> None:
        """Total=0, empty page → return []."""
        call_count = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json={"total": 0, "jobPostings": []})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

        assert result == []
        assert call_count["n"] == 1

    async def test_default_facets_absent_sends_empty_object(self) -> None:
        """Companies without default_facets POST appliedFacets={}."""
        captured: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            import json
            captured["body"] = json.loads(req.read())
            return httpx.Response(200, json={"total": 0, "jobPostings": []})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

        assert captured["body"]["appliedFacets"] == {}

    async def test_cap_breach_logs_error_and_returns_partial(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Total >> cap × page_size → stop at cap, ERROR log, return partial.

        The cap is a backstop; it must not raise. The caller still
        records a normal scrape_runs row (the pagination ceiling isn't
        an "error" in the retryable sense — just a "look at this" signal).
        """
        import logging

        def handler(req: httpx.Request) -> httpx.Response:
            # Always return a non-empty page so we keep paginating until
            # the cap stops us.
            import json
            parsed = json.loads(req.read())
            offset = parsed["offset"]
            jobs = [_job(offset + i) for i in range(WORKDAY_PAGE_SIZE)]
            # Claim a giant total so the loop wants to keep going.
            return httpx.Response(
                200,
                json={
                    "total": WORKDAY_MAX_PAGES * WORKDAY_PAGE_SIZE * 10,
                    "jobPostings": jobs,
                },
            )

        transport = httpx.MockTransport(handler)
        with caplog.at_level(logging.ERROR, logger="api.services.workday_client"):
            async with httpx.AsyncClient(transport=transport) as http:
                result = await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

        assert len(result) == WORKDAY_MAX_PAGES * WORKDAY_PAGE_SIZE
        cap_errors = [
            r for r in caplog.records
            if "pagination cap hit" in r.getMessage()
        ]
        assert len(cap_errors) == 1, (
            f"expected exactly one ERROR for cap-breach, got {len(cap_errors)}"
        )

    async def test_http_error_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Workday Down")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

    async def test_missing_jobPostings_raises_value_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"total": 0})  # no jobPostings

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(ValueError, match="jobPostings"):
                await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

    async def test_missing_total_raises_value_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobPostings": []})  # no total

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(ValueError, match="'total'"):
                await fetch_jobs(PROVIDER_CONFIG_SLACK, http)

    async def test_non_dict_payload_raises_value_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            # Some misconfigured tenant might return an array root.
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(ValueError, match="not a dict"):
                await fetch_jobs(PROVIDER_CONFIG_SLACK, http)


class TestValidateProviderConfig:
    def test_valid_config_does_not_raise(self) -> None:
        _validate_provider_config(PROVIDER_CONFIG_NVIDIA)
        _validate_provider_config(PROVIDER_CONFIG_SLACK)

    @pytest.mark.parametrize("missing_key", ["base_url", "tenant_slug", "career_site_slug"])
    def test_missing_required_key_raises(self, missing_key: str) -> None:
        cfg = dict(PROVIDER_CONFIG_SLACK)
        del cfg[missing_key]
        with pytest.raises(ValueError, match=missing_key):
            _validate_provider_config(cfg)

    def test_empty_required_value_raises(self) -> None:
        cfg = dict(PROVIDER_CONFIG_SLACK, tenant_slug="")
        with pytest.raises(ValueError, match="tenant_slug"):
            _validate_provider_config(cfg)

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            _validate_provider_config("not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# transform_to_job_listings
# ---------------------------------------------------------------------------

class TestTransform:
    def test_happy_path_preserves_required_fields(self) -> None:
        raw = [_job(1)]
        result = transform_to_job_listings(
            "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
        )
        assert len(result) == 1
        listing = result[0]

        # The transformer prefers bulletFields[0] for the id.
        assert listing.id == "JR0001"
        assert listing.title == "Software Engineer 1"
        assert listing.company == "nvidia"
        assert listing.location == "Santa Clara, CA"
        assert listing.source_id == SOURCE_ID == "workday_api"
        assert listing.status == "OPEN"
        # URL: base_url + /career_site_slug + /details/ + last externalPath segment.
        assert listing.url == (
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details/"
            "Software-Engineer-1_JR0001"
        )

    def test_falls_back_to_externalPath_last_segment_when_no_bulletFields(self) -> None:
        raw = [_job(2, bulletFields=[])]
        result = transform_to_job_listings(
            "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
        )
        assert result[0].id == "Software-Engineer-2_JR0002"

    def test_skips_posting_with_missing_title(self) -> None:
        raw = [
            _job(1, title=""),
            _job(2),
            _job(3, title=None),
        ]
        result = transform_to_job_listings(
            "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
        )
        ids = [r.id for r in result]
        assert ids == ["JR0002"]

    def test_skips_posting_with_missing_externalPath(self) -> None:
        raw = [_job(1, externalPath=None), _job(2)]
        result = transform_to_job_listings(
            "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
        )
        assert [r.id for r in result] == ["JR0002"]

    def test_drops_generic_location_count(self) -> None:
        """`"3 Locations"` is a count, not a real location — drop it."""
        raw = [
            _job(1, locationsText="3 Locations"),
            _job(2, locationsText="1 Location"),
            _job(3, locationsText="Mountain View, CA"),
        ]
        result = transform_to_job_listings(
            "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
        )
        # Same order as input; verify None / preserved.
        assert result[0].location is None
        assert result[1].location is None
        assert result[2].location == "Mountain View, CA"

    def test_details_jsonb_has_all_keys_with_documented_defaults(self) -> None:
        raw = [_job(1)]
        result = transform_to_job_listings(
            "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
        )
        d = result[0].details
        # Documented shape — every key should be present so the frontend
        # backendScraperTransformer can read uniformly across providers.
        assert set(d.keys()) == {
            "department", "team", "secondary_locations", "employment_type",
            "is_remote_eligible", "compensation_summary", "published_at",
            "description_html", "experience_level", "tags",
        }
        assert d["secondary_locations"] == []
        assert d["tags"] == []
        # `published_at` should track posted_on.
        assert d["published_at"] == result[0].posted_on

    def test_unparseable_postedOn_stores_none_and_errors(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        raw = [_job(1, postedOn="Garbage Workday Date")]
        with caplog.at_level(logging.ERROR, logger="api.services.workday_client"):
            result = transform_to_job_listings(
                "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
            )
        assert result[0].posted_on is None
        assert any(
            "data quality issue" in r.getMessage() and "postedOn" in r.getMessage()
            for r in caplog.records
        )

    def test_first_last_seen_share_now_value(self) -> None:
        result = transform_to_job_listings(
            "nvidia", [_job(1)], PROVIDER_CONFIG_NVIDIA,
            now="2026-05-19T15:00:00+00:00",
        )
        r = result[0]
        assert r.first_seen_at == r.last_seen_at == r.created_at == "2026-05-19T15:00:00+00:00"

    def test_pagination_drift_dedupes_and_logs_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two postings with identical (id, title, externalPath) are
        pagination drift — keep one, log INFO, do NOT log WARN."""
        import logging
        raw = [_job(1), _job(1)]
        with caplog.at_level(logging.INFO, logger="api.services.workday_client"):
            result = transform_to_job_listings(
                "nvidia", raw, PROVIDER_CONFIG_NVIDIA,
                now="2026-05-19T15:00:00+00:00",
            )
        assert len(result) == 1
        assert result[0].id == "JR0001"
        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "pagination-drift" in r.getMessage()
        ]
        assert len(info_records) == 1
        assert "1 pagination-drift duplicate(s)" in info_records[0].getMessage()
        warn_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warn_records, (
            f"unexpected WARN/ERROR logs on pagination drift: "
            f"{[r.getMessage() for r in warn_records]}"
        )

    def test_id_fallback_collision_dedupes_and_logs_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two postings with empty bulletFields whose externalPath last
        segment matches but with DIFFERENT titles/urls — id-fallback
        chain collapsed two distinct positions. Keep first, log WARN."""
        import logging
        # Both fall back to externalPath last segment. Same segment, but
        # the rest of the path differs so the constructed urls differ.
        raw = [
            _job(1, bulletFields=[],
                 title="Software Engineer A",
                 externalPath="/job/US-CA-Santa-Clara/dup-slug"),
            _job(2, bulletFields=[],
                 title="Software Engineer B",
                 externalPath="/job/US-NY-New-York/dup-slug"),
        ]
        with caplog.at_level(logging.WARNING, logger="api.services.workday_client"):
            result = transform_to_job_listings(
                "nvidia", raw, PROVIDER_CONFIG_NVIDIA,
                now="2026-05-19T15:00:00+00:00",
            )
        assert len(result) == 1
        # Kept entry is the first one seen.
        assert result[0].id == "dup-slug"
        assert result[0].title == "Software Engineer A"
        warn_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "id collision" in r.getMessage()
        ]
        assert len(warn_records) == 1
        msg = warn_records[0].getMessage()
        # Both (title, url) pairs must be present in the WARN payload
        # so the collision is investigable from logs alone.
        assert "Software Engineer A" in msg
        assert "Software Engineer B" in msg

    def test_distinct_jobs_pass_through_with_no_dedup_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two genuinely distinct postings → 2 listings, no dedup logs."""
        import logging
        raw = [_job(1), _job(2)]
        with caplog.at_level(logging.INFO, logger="api.services.workday_client"):
            result = transform_to_job_listings(
                "nvidia", raw, PROVIDER_CONFIG_NVIDIA,
                now="2026-05-19T15:00:00+00:00",
            )
        assert {r.id for r in result} == {"JR0001", "JR0002"}
        drift_or_collision = [
            r for r in caplog.records
            if "pagination-drift" in r.getMessage() or "id collision" in r.getMessage()
        ]
        assert not drift_or_collision, (
            f"unexpected dedup logs on distinct inputs: "
            f"{[r.getMessage() for r in drift_or_collision]}"
        )


# ---------------------------------------------------------------------------
# _parse_workday_date — must match frontend `parseWorkdayDate`
# ---------------------------------------------------------------------------

class TestParseWorkdayDate:
    NOW = datetime(2026, 5, 19, 15, 30, 0, tzinfo=timezone.utc)
    TODAY_MIDNIGHT = "2026-05-19T00:00:00.000Z"
    YESTERDAY_MIDNIGHT = "2026-05-18T00:00:00.000Z"

    def test_today(self) -> None:
        assert _parse_workday_date("Posted Today", now=self.NOW) == self.TODAY_MIDNIGHT

    def test_yesterday(self) -> None:
        assert _parse_workday_date("Posted Yesterday", now=self.NOW) == self.YESTERDAY_MIDNIGHT

    def test_n_days_ago(self) -> None:
        # "Posted 30 Days Ago" → exactly 30 days back
        assert _parse_workday_date("Posted 30 Days Ago", now=self.NOW) == "2026-04-19T00:00:00.000Z"

    def test_n_plus_days_ago_adds_one_day(self) -> None:
        # Frontend semantics: "N+ Days Ago" = 1 day beyond the N bucket.
        # 30 + 1 = 31 → 2026-04-18.
        assert _parse_workday_date("Posted 30+ Days Ago", now=self.NOW) == "2026-04-18T00:00:00.000Z"

    def test_case_insensitive(self) -> None:
        assert _parse_workday_date("posted TODAY", now=self.NOW) == self.TODAY_MIDNIGHT
        assert _parse_workday_date("POSTED 5 DAYS AGO", now=self.NOW) == "2026-05-14T00:00:00.000Z"

    def test_singular_day(self) -> None:
        # Workday sometimes returns "1 Day Ago" — singular.
        assert _parse_workday_date("Posted 1 Day Ago", now=self.NOW) == "2026-05-18T00:00:00.000Z"

    @pytest.mark.parametrize("bad", [None, "", "   ", "completely opaque"])
    def test_unparseable_returns_none(self, bad: Any) -> None:
        # Per feedback_correctness_over_dont_crash.md: unparseable
        # values land as NULL, NOT as a fake "now()" timestamp that
        # would silently land on today's row in the visualization.
        assert _parse_workday_date(bad, now=self.NOW) is None

    def test_non_string_returns_none(self) -> None:
        assert _parse_workday_date(42, now=self.NOW) is None  # type: ignore[arg-type]
        assert _parse_workday_date(True, now=self.NOW) is None  # type: ignore[arg-type]

    def test_iso_string_passes_through(self) -> None:
        # If a tenant ever ships an actual ISO timestamp, honor it.
        out = _parse_workday_date("2026-01-15T14:30:00Z", now=self.NOW)
        assert out == "2026-01-15T14:30:00.000Z"

    def test_naive_now_is_treated_as_utc(self) -> None:
        # Tests pass `now=datetime(...)` without tzinfo on some
        # platforms; the helper must not crash.
        naive = datetime(2026, 5, 19, 15, 30, 0)
        assert _parse_workday_date("Posted Today", now=naive) == self.TODAY_MIDNIGHT
