"""Unit tests for the Workday fetch + transform service."""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from api.config import settings
from api.services import workday_client
from api.services.workday_client import (
    SOURCE_ID,
    WorkdayBlockedError,
    WorkdayRateLimitedError,
    WORKDAY_MAX_PAGES,
    WORKDAY_PAGE_SIZE,
    _parse_workday_date,
    _validate_provider_config,
    fetch_jobs,
    transform_to_job_listings,
    workday_http_client,
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


def _instant(value: str) -> datetime:
    """An ISO string as the moment it names, ignoring how it is spelled."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


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
            "team", "secondary_locations", "employment_type",
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

    def test_plus_bucket_stores_none_without_erroring(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The `30+` bucket is expected, not a data-quality failure.

        Two things at once: the row survives with `posted_on = None`, and
        it does NOT log an ERROR. 42.3% of open prod Workday rows sit in
        this bucket, so an ERROR here would be a per-tick log flood that
        buries the genuinely-unparseable case above.
        """
        import logging
        raw = [_job(1, postedOn="Posted 30+ Days Ago")]
        with caplog.at_level(logging.ERROR, logger="api.services.workday_client"):
            result = transform_to_job_listings(
                "nvidia", raw, PROVIDER_CONFIG_NVIDIA, now="2026-05-19T15:00:00+00:00",
            )
        # Per-row degradation only — the row is still emitted, still OPEN.
        assert len(result) == 1
        assert result[0].posted_on is None
        assert result[0].details["published_at"] is None
        assert [r.getMessage() for r in caplog.records if r.levelname == "ERROR"] == []

    def test_first_seen_at_is_the_board_date_while_the_rest_share_now(self) -> None:
        """``first_seen_at`` is the EFFECTIVE POSTED DATE (POSTED-DATE-PLAN §2).

        Previously this asserted all three equalled the injected ``now``. Under
        D9 ``first_seen_at`` follows ``postedOn`` instead — for Workday that is
        the 57.7% of rows carrying a real relative date.

        Asserted against ``posted_on`` rather than a literal because the ``now``
        seam does NOT reach the date parser: ``_parse_workday_date`` takes no
        reference instant, so ``"Posted Today"`` resolves against the wall clock
        while ``created_at`` is the injected value. That pre-existing asymmetry
        is why a hard-coded date here would be a calendar-dependent flake.
        """
        r = transform_to_job_listings(
            "nvidia", [_job(1)], PROVIDER_CONFIG_NVIDIA,
            now="2026-05-19T15:00:00+00:00",
        )[0]

        assert r.posted_on is not None, "'Posted Today' is a real date, not a bucket"
        # Compared as INSTANTS: this client writes "...T00:00:00.000Z" while the
        # shared helper emits "+00:00". Both are the same moment and both are
        # equally valid input to a TIMESTAMPTZ; a string compare here would fail
        # on spelling and say nothing about the behaviour under test.
        assert _instant(r.first_seen_at) == _instant(r.posted_on)
        assert r.last_seen_at == r.created_at == "2026-05-19T15:00:00+00:00"
        assert r.first_seen_at != r.created_at

    def test_the_30_plus_bucket_seeds_first_sight_not_a_fabricated_date(self) -> None:
        """§3, and the whole Workday trust story in one assertion.

        ``"Posted 30+ Days Ago"`` is a bucket BOUNDARY. U5a made
        ``_parse_workday_date`` return None for it; U3 must therefore land those
        rows — 42.3% of open Workday rows — on first sight. The failure this
        guards is subtle and silent: seeding ``now - 31d`` would look like a
        perfectly ordinary posting date and nothing downstream could tell.
        """
        r = transform_to_job_listings(
            "nvidia", [_job(2, postedOn="Posted 30+ Days Ago")], PROVIDER_CONFIG_NVIDIA,
            now="2026-05-19T15:00:00+00:00",
        )[0]

        assert r.posted_on is None
        assert r.first_seen_at == r.created_at == "2026-05-19T15:00:00+00:00"

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
        # "Posted N Days Ago" IS a date — an exact day offset. This is the
        # 57.7% of prod Workday rows that keep an accurate posted date.
        assert _parse_workday_date("Posted 3 Days Ago", now=self.NOW) == "2026-05-16T00:00:00.000Z"
        assert _parse_workday_date("Posted 30 Days Ago", now=self.NOW) == "2026-04-19T00:00:00.000Z"

    @pytest.mark.parametrize(
        "bucket",
        ["Posted 30+ Days Ago", "Posted 7+ Days Ago", "posted 30+ days ago"],
    )
    def test_n_plus_days_ago_is_a_bucket_not_a_date(self, bucket: str) -> None:
        # "N+ Days Ago" is the label of Workday's open-ended oldest bucket,
        # not a posting date. We used to answer `today - (N + 1)`, which
        # invented a precise timestamp — 42.3% of open prod Workday rows all
        # claiming to be exactly 31 days old, sliding forward daily.
        # NULL is the honest answer; the caller falls back to first sight.
        assert _parse_workday_date(bucket, now=self.NOW) is None

    def test_plus_bucket_does_not_fall_back_to_now(self) -> None:
        # The failure mode that matters: a rejected bucket must NOT quietly
        # become "today". None, and only None.
        out = _parse_workday_date("Posted 30+ Days Ago", now=self.NOW)
        assert out is None
        assert out != self.TODAY_MIDNIGHT

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

    def test_a_subsecond_iso_string_is_still_a_valid_timestamp(self) -> None:
        """The ISO branch with microseconds — the shape that used to be unstorable.

        ``datetime.fromisoformat`` keeps whatever precision the board sent, and the old
        ``.isoformat().replace("+00:00", ".000Z")`` appended a SECOND fractional part to
        it: ``2026-01-15T14:30:00.789000.000Z``. Postgres rejects that outright, and
        ``upsert_jobs_batch`` writes the whole harvest in one statement with no per-row
        fallback — so one such row fails the entire tenant's batch, not just itself.
        """
        out = _parse_workday_date("2026-01-15T14:30:00.789000Z", now=self.NOW)
        assert out == "2026-01-15T14:30:00.789Z"
        assert out.count(".") == 1

    def test_an_offset_iso_string_is_converted_not_string_patched(self) -> None:
        """A non-UTC offset must be MOVED to UTC, not have its suffix swapped.

        ``+02:00`` never contained the literal the old ``replace`` was hunting for, so
        this depended entirely on ``astimezone`` having already run. Pinned so the
        conversion cannot be dropped as "the replace handles it".
        """
        assert (
            _parse_workday_date("2026-01-15T14:30:00+02:00", now=self.NOW)
            == "2026-01-15T12:30:00.000Z"
        )

    @pytest.mark.parametrize(
        "raw",
        [
            "Posted Today",
            "Posted Yesterday",
            "Posted 3 Days Ago",
            "2026-01-15T14:30:00Z",
            "2026-01-15T14:30:00.789000Z",
            "2026-01-15T14:30:00.000001Z",
            "2026-01-15T14:30:00+02:00",
            "2026-01-15",
        ],
    )
    def test_every_branch_emits_a_timestamp_postgres_accepts(self, raw: str, db_conn) -> None:
        """The invariant that actually matters, checked against a real Postgres.

        Not "the string looks right" — ``posted_on`` is written straight into a
        ``timestamptz`` column, so the only question is whether the server parses it.
        The cast is the whole test; it raises ``DataError`` on the old output.
        """
        out = _parse_workday_date(raw, now=self.NOW)
        assert out is not None
        cur = db_conn.cursor()
        try:
            cur.execute("SELECT %s::timestamptz AS t", (out,))
            assert cur.fetchone()["t"] is not None
        finally:
            # The connection is module-scoped, and a rejected cast aborts the whole
            # transaction — without this the FIRST bad value would cascade into every
            # later test on this fixture and hide which one actually caught it.
            db_conn.rollback()

    def test_naive_now_is_treated_as_utc(self) -> None:
        # Tests pass `now=datetime(...)` without tzinfo on some
        # platforms; the helper must not crash.
        naive = datetime(2026, 5, 19, 15, 30, 0)
        assert _parse_workday_date("Posted Today", now=naive) == self.TODAY_MIDNIGHT


# ---------------------------------------------------------------------------
# fetch_jobs — 429 handling (retry in place, Retry-After, pod cooldown)
# ---------------------------------------------------------------------------

class TestFetchJobsRateLimit:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> list[float]:
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(workday_client.asyncio, "sleep", fake_sleep)
        self.slept = slept
        return slept

    async def test_429_then_200_retries_and_honors_retry_after(self) -> None:
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
            return httpx.Response(200, json={"total": 1, "jobPostings": [_job(1)]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

        assert len(result) == 1
        assert calls["n"] == 2
        assert self.slept == [7.0]

    async def test_retry_after_is_capped(self) -> None:
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "3600"})
            return httpx.Response(200, json={"total": 0, "jobPostings": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

        assert self.slept == [workday_client.WORKDAY_429_MAX_SLEEP_SECONDS]

    async def test_persistent_429_raises_after_bounded_retries(self) -> None:
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WorkdayRateLimitedError):
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

        assert calls["n"] == workday_client.WORKDAY_429_MAX_RETRIES + 1
        # No Retry-After → jittered exponential backoff, each under its ceiling.
        assert len(self.slept) == workday_client.WORKDAY_429_MAX_RETRIES
        for attempt, s in enumerate(self.slept):
            assert 0 <= s <= workday_client.WORKDAY_429_BACKOFF_BASE_SECONDS * 2 ** attempt

    async def test_cooldown_short_circuits_same_pod_only(self) -> None:
        hosts: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            hosts.append(req.url.host)
            if req.url.host.endswith("wd5.myworkdayjobs.com"):
                return httpx.Response(429)
            return httpx.Response(200, json={"total": 0, "jobPostings": []})

        other_tenant_same_pod = {
            "base_url": "https://acme.wd5.myworkdayjobs.com",
            "tenant_slug": "acme",
            "career_site_slug": "External",
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WorkdayRateLimitedError):
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
            n_after_trip = len(hosts)

            # Same pod, different tenant: fails fast, zero requests.
            with pytest.raises(WorkdayRateLimitedError, match="cooling down"):
                await fetch_jobs(other_tenant_same_pod, http)
            assert len(hosts) == n_after_trip

            # Different pod (wd12): unaffected.
            assert await fetch_jobs(PROVIDER_CONFIG_SLACK, http) == []
            assert len(hosts) == n_after_trip + 1

    async def test_cooldown_expires(self) -> None:
        workday_client._cooldown_until["wd5.myworkdayjobs.com"] = 0.0  # in the past

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"total": 0, "jobPostings": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            assert await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http) == []
        assert "wd5.myworkdayjobs.com" not in workday_client._cooldown_until

    async def test_rate_limited_error_is_an_httpx_error(self) -> None:
        # Existing `except httpx.HTTPError` handlers in the tasks must catch it.
        assert issubclass(WorkdayRateLimitedError, httpx.HTTPError)

    async def test_pod_key(self) -> None:
        assert (
            workday_client._pod_key("https://nvidia.wd5.myworkdayjobs.com/wday/cxs/x/y/jobs")
            == "wd5.myworkdayjobs.com"
        )
        assert workday_client._pod_key("https://jobs.example.com/a") == "jobs.example.com"

    async def test_retry_after_http_date(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        assert workday_client._retry_after_seconds(resp) == 0.0
        assert workday_client._retry_after_seconds(httpx.Response(429)) is None
        bad = httpx.Response(429, headers={"Retry-After": "soon"})
        assert workday_client._retry_after_seconds(bad) is None


# ---------------------------------------------------------------------------
# Non-2xx diagnostics — who issued the block, Cloudflare or Workday?
# ---------------------------------------------------------------------------

class TestNon2xxDiagnostics:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_sleep(seconds: float) -> None:
            return None

        monkeypatch.setattr(workday_client.asyncio, "sleep", fake_sleep)

    async def _diag_records(
        self, caplog: pytest.LogCaptureFixture, response: httpx.Response
    ) -> list[Any]:
        import logging

        def handler(req: httpx.Request) -> httpx.Response:
            return response

        with caplog.at_level(logging.WARNING, logger="api.services.workday_client"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                with pytest.raises(httpx.HTTPError):
                    await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
        return [r for r in caplog.records if "non-2xx" in r.getMessage()]

    async def test_cloudflare_challenge_429_is_logged_with_headers_and_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        response = httpx.Response(
            429,
            headers=[
                ("Server", "cloudflare"),
                ("CF-RAY", "abc123-IAH"),
                ("cf-mitigated", "challenge"),
                ("Retry-After", "30"),
                ("Set-Cookie", "__cf_bm=SECRETVALUE; path=/; HttpOnly"),
                ("Set-Cookie", "other=ALSOSECRET"),
                ("Authorization", "Bearer SECRETTOKEN"),
            ],
            text="<html><title>Just a moment...</title></html>",
        )
        records = await self._diag_records(caplog, response)

        # A challenge with no proxy is not retried: exactly one request.
        assert len(records) == 1
        msg = records[0].getMessage()
        assert records[0].levelname == "WARNING"
        assert "status=429" in msg
        assert "blocker=cloudflare" in msg
        assert "host=nvidia.wd5.myworkdayjobs.com" in msg
        assert "'cf-ray': 'abc123-IAH'" in msg
        assert "'cf-mitigated': 'challenge'" in msg
        assert "'retry-after': '30'" in msg
        assert "'set-cookie': '__cf_bm, other'" in msg
        assert "Just a moment" in msg
        # Secrets never logged.
        assert "SECRETVALUE" not in msg
        assert "ALSOSECRET" not in msg
        assert "SECRETTOKEN" not in msg

    async def test_cloudflare_headers_alone_do_not_mean_cloudflare_blocked(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Workday is behind Cloudflare: Server/CF-RAY are on every response.
        # A 429 that reached Workday's origin carries x-wd-request-id.
        response = httpx.Response(
            429,
            headers={
                "Server": "cloudflare",
                "CF-RAY": "abc123-IAH",
                "x-wd-request-id": "VPS|00000000-0000-0000-0000-000000000000",
            },
            json={"errorCode": "TOO_MANY_REQUESTS"},
        )
        msg = (await self._diag_records(caplog, response))[0].getMessage()
        assert "blocker=workday" in msg

    async def test_body_is_truncated_and_unknown_without_markers(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        response = httpx.Response(503, text="x" * 5000)
        records = await self._diag_records(caplog, response)
        assert len(records) == 1  # non-429: logged once, no retry
        msg = records[0].getMessage()
        assert "status=503" in msg
        assert "blocker=unknown" in msg
        assert "x" * 1000 in msg
        assert "x" * 1001 not in msg

    async def test_success_is_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"total": 0, "jobPostings": []})

        with caplog.at_level(logging.WARNING, logger="api.services.workday_client"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
        assert not [r for r in caplog.records if "non-2xx" in r.getMessage()]

    def test_cloudflare_rate_limit_error_page_body(self) -> None:
        resp = httpx.Response(429, text="error code: 1015")
        assert workday_client._diag_blocker(resp, resp.text) == "cloudflare"


# ---------------------------------------------------------------------------
# Egress proxy (WORKDAY_PROXY_URL) and Cloudflare challenge ≠ rate limit
# ---------------------------------------------------------------------------

_SECRET_PROXY = "http://user:secret@proxy.example.net:8080"

_CHALLENGE_HEADERS = {
    "Server": "cloudflare",
    "cf-mitigated": "challenge",
}


def _challenge() -> httpx.Response:
    return httpx.Response(
        429, headers=_CHALLENGE_HEADERS,
        text="<html><title>Just a moment...</title></html>",
    )


def _closed_loopback_port() -> int:
    """A loopback port nothing listens on, so a proxied request fails locally."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestWorkdayHttpClient:
    def _record_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        class _Recorder(httpx.AsyncClient):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                calls.append(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(workday_client.httpx, "AsyncClient", _Recorder)
        return calls

    @pytest.mark.parametrize("value", [None, SecretStr(""), SecretStr("   ")])
    async def test_unset_or_empty_is_direct(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
        value: SecretStr | None,
    ) -> None:
        monkeypatch.setattr(settings, "workday_proxy_url", value)
        calls = self._record_kwargs(monkeypatch)
        with caplog.at_level(logging.INFO, logger="api.services.workday_client"):
            async with workday_http_client():
                pass
        assert calls == [{}]
        assert "Workday egress=direct" in caplog.text

    async def test_set_builds_a_proxied_client_and_logs_host_only(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(settings, "workday_proxy_url", SecretStr(_SECRET_PROXY))
        calls = self._record_kwargs(monkeypatch)
        with caplog.at_level(logging.DEBUG):
            async with workday_http_client():
                pass
        assert calls == [{"proxy": _SECRET_PROXY}]
        assert "Workday egress=proxy host=proxy.example.net" in caplog.text
        assert "secret" not in caplog.text
        assert "user:" not in caplog.text

    async def test_invalid_proxy_url_error_has_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # httpx's own message for a bad scheme echoes the whole URL.
        monkeypatch.setattr(
            settings, "workday_proxy_url", SecretStr("ftp://user:secret@proxy.example.net:21"),
        )
        with pytest.raises(ValueError) as exc_info:
            workday_http_client()
        assert "secret" not in str(exc_info.value)
        assert "proxy.example.net" in str(exc_info.value)
        assert exc_info.value.__suppress_context__

    async def test_proxy_failure_logs_no_credentials_and_does_not_go_direct(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        port = _closed_loopback_port()
        monkeypatch.setattr(
            settings, "workday_proxy_url",
            SecretStr(f"http://user:secret@127.0.0.1:{port}"),
        )
        with caplog.at_level(logging.DEBUG):
            async with workday_http_client() as http:
                # A connect error to the proxy surfaces as-is: no fallback to
                # direct, and it's an httpx.HTTPError the task records.
                with pytest.raises(httpx.ConnectError):
                    await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
            logging.getLogger("api.tasks.fetch_workday_company").error(
                "fetch_workday_company failed", exc_info=True,
            )
        formatter = logging.Formatter()
        for record in caplog.records:
            rendered = formatter.format(record)
            assert "secret" not in rendered
            assert "user:" not in rendered


class TestCloudflareChallenge:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(workday_client.asyncio, "sleep", fake_sleep)
        self.slept = slept

    def _counting(self, *responses: httpx.Response) -> tuple[dict[str, int], Any]:
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return responses[min(calls["n"], len(responses)) - 1]

        return calls, handler

    async def test_no_proxy_raises_blocked_after_exactly_one_request(self) -> None:
        calls, handler = self._counting(_challenge())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WorkdayBlockedError) as exc_info:
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

        assert calls["n"] == 1
        assert self.slept == []
        assert workday_client._cooldown_until == {}
        msg = str(exc_info.value)
        assert "Cloudflare challenge" in msg
        assert "nvidia.wd5.myworkdayjobs.com" in msg
        assert "egress=direct" in msg

    async def test_proxy_retries_in_place_then_raises_without_cooldown(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "workday_proxy_url", SecretStr(_SECRET_PROXY))
        calls, handler = self._counting(_challenge())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WorkdayBlockedError) as exc_info:
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

            assert calls["n"] == workday_client.WORKDAY_429_MAX_RETRIES + 1
            assert len(self.slept) == workday_client.WORKDAY_429_MAX_RETRIES
            assert workday_client._cooldown_until == {}
            assert "egress=proxy" in str(exc_info.value)
            assert "secret" not in str(exc_info.value)

            # The pod is not cooled down: another tenant on wd5 still fetches.
            ok_calls = {"n": 0}

            def ok(req: httpx.Request) -> httpx.Response:
                ok_calls["n"] += 1
                return httpx.Response(200, json={"total": 0, "jobPostings": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(ok)) as http:
            other_tenant_same_pod = {
                "base_url": "https://acme.wd5.myworkdayjobs.com",
                "tenant_slug": "acme",
                "career_site_slug": "External",
            }
            assert await fetch_jobs(other_tenant_same_pod, http) == []
        assert ok_calls["n"] == 1

    async def test_proxy_challenge_then_200_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "workday_proxy_url", SecretStr(_SECRET_PROXY))
        calls, handler = self._counting(
            _challenge(), httpx.Response(200, json={"total": 1, "jobPostings": [_job(1)]}),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
        assert len(result) == 1
        assert calls["n"] == 2

    async def test_403_challenge_is_blocked_too(self) -> None:
        calls, handler = self._counting(
            httpx.Response(403, headers=_CHALLENGE_HEADERS, text="Just a moment..."),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WorkdayBlockedError):
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
        assert calls["n"] == 1

    async def test_cloudflare_5xx_error_page_is_not_a_challenge(self) -> None:
        # 52x origin-down pages carry Cloudflare markup but say nothing about
        # our IP: a plain HTTPStatusError, so Procrastinate still re-runs it.
        calls, handler = self._counting(
            httpx.Response(522, text='<div id="cf-error-details">timed out</div>'),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)
        assert calls["n"] == 1

    @pytest.mark.parametrize("proxied", [False, True])
    async def test_plain_429_still_retries_then_cools_down_the_pod(
        self, monkeypatch: pytest.MonkeyPatch, proxied: bool,
    ) -> None:
        if proxied:
            monkeypatch.setattr(settings, "workday_proxy_url", SecretStr(_SECRET_PROXY))
        calls, handler = self._counting(
            httpx.Response(429, headers={"x-wd-request-id": "VPS|0"}),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WorkdayRateLimitedError) as exc_info:
                await fetch_jobs(PROVIDER_CONFIG_NVIDIA, http)

        assert not isinstance(exc_info.value, WorkdayBlockedError)
        assert calls["n"] == workday_client.WORKDAY_429_MAX_RETRIES + 1
        assert "wd5.myworkdayjobs.com" in workday_client._cooldown_until

    async def test_blocked_error_is_a_rate_limited_error(self) -> None:
        assert issubclass(WorkdayBlockedError, WorkdayRateLimitedError)
