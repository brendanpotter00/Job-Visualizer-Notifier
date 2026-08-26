"""Unit tests for the Eightfold fetch + transform service.

Covers:
- SSRF allowlist (load-bearing security guarantee after Unit 7 deletes the
  Vercel proxy)
- Sequential pagination (10/page cap, partial-page detection, total-based
  stop, MAX_PAGES backstop)
- HTTP / payload error paths
- Transform: id extraction, location normalization, t_create parsing,
  isPrivate filtering, missing-field filtering
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from api.services import eightfold_client
from api.services.eightfold_client import (
    EIGHTFOLD_PAGE_SIZE,
    MAX_PAGES,
    SOURCE_ID,
    _is_allowed_eightfold_host,
    _parse_eightfold_epoch,
    fetch_jobs,
    transform_to_job_listings,
)


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


def _make_position(idx: int, **overrides: Any) -> dict[str, Any]:
    """Build a minimally-valid Eightfold position dict."""
    base = {
        "id": idx,
        "ats_job_id": f"req-{idx}",
        "display_job_id": f"R{idx:04d}",
        "name": f"Senior Software Engineer {idx}",
        "canonicalPositionUrl": f"https://explore.jobs.netflix.net/jobs/{idx}",
        "location": "Los Angeles,California,United States",
        "locations": ["Los Angeles,California,United States"],
        "department": "Engineering",
        "team": "Platform",
        "is_remote_eligible": False,
        "show_remote_eligibility": False,
        "t_create": 1_700_000_000,  # 2023-11-14 ish UTC
        "isPrivate": False,
    }
    base.update(overrides)
    return base


def _client_with_handler(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# ----------------------------------------------------------------------------
# SSRF allowlist
# ----------------------------------------------------------------------------


class TestSSRFAllowlist:
    """SSRF allowlist matches ``api/eightfold.ts`` 1:1.

    After Unit 7 deletes the Vercel proxy, this Python check is the ONLY
    defense against a wrong ``tenant_host`` becoming an SSRF.
    """

    @pytest.mark.parametrize(
        "host",
        [
            "eightfold.ai",
            "subdomain.eightfold.ai",
            "tenant.api.eightfold.ai",
            "explore.jobs.netflix.net",
            "EXPLORE.JOBS.NETFLIX.NET",  # lowercase normalization
            "  subdomain.eightfold.ai  ",  # strip whitespace
        ],
    )
    def test_allowed_hosts(self, host: str) -> None:
        assert _is_allowed_eightfold_host(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "evil.com",
            "",
            None,
            "eightfold.ai.evil.com",  # suffix bypass attempt
            "evil-eightfold.ai",  # similar-looking
            "jobs.netflix.net",  # subdomain of vanity but not exact match
            "explore.jobs.netflix.com",  # wrong TLD
            "127.0.0.1",
            "localhost",
            "169.254.169.254",  # AWS IMDS — classic SSRF target
        ],
    )
    def test_rejected_hosts(self, host: Any) -> None:
        assert _is_allowed_eightfold_host(host) is False


# ----------------------------------------------------------------------------
# fetch_jobs: SSRF + pagination
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchJobsSSRF:
    async def test_rejects_invalid_tenant_host_before_http(self):
        """SSRF check fires BEFORE any HTTP call (asserted by handler abuse)."""
        called = {"hits": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            called["hits"] += 1
            return httpx.Response(200, json={"count": 0, "positions": []})

        async with _client_with_handler(handler) as http:
            with pytest.raises(ValueError, match="not on the SSRF allowlist"):
                await fetch_jobs("evil.com", "netflix.com", http)

        assert called["hits"] == 0, (
            "fetch_jobs should reject pre-HTTP — handler must not fire"
        )

    async def test_rejects_empty_domain(self):
        async with _client_with_handler(
            lambda r: httpx.Response(200, json={"count": 0, "positions": []})
        ) as http:
            with pytest.raises(ValueError, match="non-empty domain"):
                await fetch_jobs("explore.jobs.netflix.net", "", http)


@pytest.mark.asyncio
class TestFetchJobsPagination:
    async def test_happy_path_three_pages(self):
        """Three pages (10 + 10 + 5), total reported as 25."""
        captured_offsets: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "explore.jobs.netflix.net"
            assert request.url.path == "/api/apply/v2/jobs"
            assert request.url.params["domain"] == "netflix.com"
            assert request.url.params["num"] == str(EIGHTFOLD_PAGE_SIZE)
            offset = int(request.url.params["start"])
            captured_offsets.append(offset)

            if offset == 0:
                positions = [_make_position(i) for i in range(10)]
            elif offset == 10:
                positions = [_make_position(i) for i in range(10, 20)]
            elif offset == 20:
                positions = [_make_position(i) for i in range(20, 25)]
            else:
                pytest.fail(f"unexpected offset {offset}")
            return httpx.Response(200, json={"count": 25, "positions": positions})

        async with _client_with_handler(handler) as http:
            result = await fetch_jobs(
                "explore.jobs.netflix.net", "netflix.com", http
            )

        assert len(result) == 25
        assert captured_offsets == [0, 10, 20]

    async def test_stops_on_partial_page_even_when_count_overreports(self):
        """Eightfold sometimes over-reports count — partial page wins."""

        def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params["start"])
            if offset == 0:
                # Server lies: count=100 but actually only returns 7 rows.
                positions = [_make_position(i) for i in range(7)]
                return httpx.Response(
                    200, json={"count": 100, "positions": positions}
                )
            # Should never reach here.
            return httpx.Response(200, json={"count": 100, "positions": []})

        async with _client_with_handler(handler) as http:
            result = await fetch_jobs(
                "explore.jobs.netflix.net", "netflix.com", http
            )
        assert len(result) == 7

    async def test_stops_on_empty_page(self):
        """First empty page short-circuits the loop."""
        pages_served = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            pages_served["n"] += 1
            return httpx.Response(200, json={"count": 0, "positions": []})

        async with _client_with_handler(handler) as http:
            result = await fetch_jobs(
                "explore.jobs.netflix.net", "netflix.com", http
            )
        assert result == []
        # First page was empty → break, so only one page was fetched.
        assert pages_served["n"] == 1

    async def test_stops_when_total_reached(self):
        """``len(all_positions) >= count`` breaks the loop."""

        def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params["start"])
            assert offset == 0
            positions = [_make_position(i) for i in range(10)]
            return httpx.Response(200, json={"count": 10, "positions": positions})

        async with _client_with_handler(handler) as http:
            result = await fetch_jobs(
                "explore.jobs.netflix.net", "netflix.com", http
            )
        assert len(result) == 10

    async def test_max_pages_returns_partial_with_error_log(self, caplog):
        """MAX_PAGES cap returns partial result and emits ERROR log."""
        monkeypatched = 5

        # Monkeypatch MAX_PAGES low for the test so we don't have to mock
        # 100 round-trips.
        original_max = eightfold_client.MAX_PAGES
        eightfold_client.MAX_PAGES = monkeypatched
        try:
            def handler(request: httpx.Request) -> httpx.Response:
                # Every page returns a full 10 rows and an over-reported
                # count — guarantees no natural break.
                offset = int(request.url.params["start"])
                positions = [_make_position(offset + i) for i in range(10)]
                return httpx.Response(
                    200, json={"count": 999_999, "positions": positions}
                )

            import logging
            with caplog.at_level(logging.ERROR, logger=eightfold_client.__name__):
                async with _client_with_handler(handler) as http:
                    result = await fetch_jobs(
                        "explore.jobs.netflix.net", "netflix.com", http
                    )
        finally:
            eightfold_client.MAX_PAGES = original_max

        assert len(result) == monkeypatched * EIGHTFOLD_PAGE_SIZE
        assert any(
            "MAX_PAGES" in rec.message and rec.levelname == "ERROR"
            for rec in caplog.records
        ), "expected ERROR log mentioning MAX_PAGES"

    async def test_raises_on_5xx(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server boom"})

        async with _client_with_handler(handler) as http:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_jobs(
                    "explore.jobs.netflix.net", "netflix.com", http
                )

    async def test_raises_on_missing_positions_key(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"count": 5})

        async with _client_with_handler(handler) as http:
            with pytest.raises(ValueError, match="missing 'positions'"):
                await fetch_jobs(
                    "explore.jobs.netflix.net", "netflix.com", http
                )

    async def test_raises_on_non_list_positions(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"count": 5, "positions": "oops"}
            )

        async with _client_with_handler(handler) as http:
            with pytest.raises(ValueError, match="'positions' is not a list"):
                await fetch_jobs(
                    "explore.jobs.netflix.net", "netflix.com", http
                )

    async def test_falls_back_when_count_missing(self):
        """Missing or non-int ``count`` should NOT abort the fetch — partial-page detection still terminates the loop."""

        def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params["start"])
            if offset == 0:
                # No 'count' key at all.
                return httpx.Response(
                    200, json={"positions": [_make_position(i) for i in range(5)]}
                )
            pytest.fail("should not request more than one page")

        async with _client_with_handler(handler) as http:
            result = await fetch_jobs(
                "explore.jobs.netflix.net", "netflix.com", http
            )
        # Partial page (5 < 10) breaks the loop.
        assert len(result) == 5


# ----------------------------------------------------------------------------
# transform_to_job_listings
# ----------------------------------------------------------------------------


class TestTransform:
    def test_happy_path_minimal_position(self):
        pos = _make_position(1)
        jobs = transform_to_job_listings("netflix", [pos])
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == "1"
        assert job.source_id == SOURCE_ID  # "eightfold_api"
        assert job.company == "netflix"
        assert job.title.startswith("Senior Software Engineer")
        assert job.url.startswith("https://explore.jobs.netflix.net/")
        assert job.location == "Los Angeles, California, United States"
        assert job.posted_on is not None
        assert job.posted_on.endswith("+00:00") or job.posted_on.endswith("Z")
        # ``details`` contract
        assert job.details["is_remote_eligible"] is False
        assert job.details["department"] == "Engineering"
        assert job.details["t_create_raw"] == 1_700_000_000

    def test_id_fallback_chain(self):
        # No top-level id, but ats_job_id present.
        pos = _make_position(2, id=None, ats_job_id="ATS-42")
        jobs = transform_to_job_listings("netflix", [pos])
        assert len(jobs) == 1
        assert jobs[0].id == "ATS-42"

        # Both id and ats_job_id missing, but display_job_id present.
        pos2 = _make_position(3, id=None, ats_job_id=None, display_job_id="D-7")
        jobs2 = transform_to_job_listings("netflix", [pos2])
        assert jobs2[0].id == "D-7"

    def test_drops_position_with_no_id_sources(self):
        pos = _make_position(
            4, id=None, ats_job_id=None, display_job_id=None
        )
        jobs = transform_to_job_listings("netflix", [pos])
        assert jobs == []

    def test_drops_private_position(self):
        pos = _make_position(5, isPrivate=True)
        jobs = transform_to_job_listings("netflix", [pos])
        assert jobs == []

    def test_drops_position_with_missing_name(self):
        pos = _make_position(6, name="")
        assert transform_to_job_listings("netflix", [pos]) == []
        pos2 = _make_position(7, name=None)
        assert transform_to_job_listings("netflix", [pos2]) == []

    def test_drops_position_with_missing_url(self):
        pos = _make_position(8, canonicalPositionUrl="")
        assert transform_to_job_listings("netflix", [pos]) == []

    def test_handles_non_dict_entries_defensively(self):
        jobs = transform_to_job_listings("netflix", ["not a dict", 42, None])  # type: ignore[arg-type]
        assert jobs == []

    def test_is_remote_eligible_coercion(self):
        # Either truthy field sets it to True.
        pos1 = _make_position(9, is_remote_eligible=True)
        assert transform_to_job_listings("netflix", [pos1])[0].details[
            "is_remote_eligible"
        ] is True

        pos2 = _make_position(10, is_remote_eligible=False, show_remote_eligibility=1)
        assert transform_to_job_listings("netflix", [pos2])[0].details[
            "is_remote_eligible"
        ] is True

        pos3 = _make_position(11, is_remote_eligible=None, show_remote_eligibility=None)
        assert transform_to_job_listings("netflix", [pos3])[0].details[
            "is_remote_eligible"
        ] is False

    def test_location_falls_back_to_locations_array(self):
        pos = _make_position(
            12, location=None, locations=["San Jose,California,United States"]
        )
        jobs = transform_to_job_listings("netflix", [pos])
        assert jobs[0].location == "San Jose, California, United States"

    def test_location_none_when_all_missing(self):
        pos = _make_position(13, location=None, locations=None)
        jobs = transform_to_job_listings("netflix", [pos])
        assert jobs[0].location is None


# ----------------------------------------------------------------------------
# transform dedup (incident 2026-05-20: CardinalityViolation on first Netflix
# fetch — see docs/incidents/2026-05-20-eightfold-upsert-cardinality-violation.md)
# ----------------------------------------------------------------------------


class TestTransformDedup:
    """Transformer dedups duplicate job_ids and distinguishes the two
    failure modes:

    - Pagination drift (same id, same title+url) — Eightfold's offset-paginated
      ``/api/apply/v2/jobs`` can return a single underlying position on two
      adjacent pages when the dataset shifts between page fetches. Expected on
      a live tenant; logged INFO.
    - Id fallback chain collapse (same id, different title or url) — two
      genuinely distinct raw positions resolve to the same job_id because
      ``_extract_eightfold_id`` walked through to ``ats_job_id`` /
      ``display_job_id`` and they happened to match another row's primary id.
      Silent data corruption; logged WARN with both (title, url) pairs.
    """

    def test_pagination_drift_dedup_keeps_first_and_logs_info(self, caplog):
        # Same position appears twice with identical title + url — drift.
        pos1 = _make_position(100)
        pos2 = _make_position(100)  # exact same id, name, canonicalPositionUrl

        with caplog.at_level(
            "INFO", logger="api.services.eightfold_client"
        ):
            jobs = transform_to_job_listings("netflix", [pos1, pos2])

        assert len(jobs) == 1
        assert jobs[0].id == "100"

        info_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "INFO" and "pagination-drift" in r.getMessage()
        ]
        assert len(info_msgs) == 1
        assert "1 pagination-drift duplicate(s)" in info_msgs[0]

        # No WARN should fire for benign drift.
        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "id collision" in r.getMessage()
        ]
        assert warn_msgs == []

    def test_id_fallback_collision_keeps_first_and_logs_warn(self, caplog):
        # First row has primary id "X". Second row has no primary id but its
        # ats_job_id is also "X" — the fallback chain collapses them onto
        # the same composite key, but they are genuinely different positions
        # (different title + different canonicalPositionUrl).
        first = _make_position(
            14,
            id="X",
            name="Real Position Title",
            canonicalPositionUrl="https://explore.jobs.netflix.net/jobs/real",
        )
        second = _make_position(
            15,
            id=None,
            ats_job_id="X",  # collides via fallback chain
            display_job_id="other-display",
            name="Different Position Title",
            canonicalPositionUrl="https://explore.jobs.netflix.net/jobs/other",
        )

        with caplog.at_level(
            "WARNING", logger="api.services.eightfold_client"
        ):
            jobs = transform_to_job_listings("netflix", [first, second])

        assert len(jobs) == 1
        # First-wins.
        assert jobs[0].id == "X"
        assert jobs[0].title == "Real Position Title"
        assert jobs[0].url == "https://explore.jobs.netflix.net/jobs/real"

        warn_records = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "id collision" in r.getMessage()
        ]
        assert len(warn_records) == 1
        msg = warn_records[0].getMessage()
        # Both titles must appear so the log is investigable on its own.
        assert "Real Position Title" in msg
        assert "Different Position Title" in msg
        assert "id='X'" in msg or "id=\"X\"" in msg

    def test_unique_positions_are_not_logged(self, caplog):
        """Happy path: no dedup → no INFO drift line, no WARN collision line."""
        positions = [_make_position(i) for i in range(200, 205)]

        with caplog.at_level(
            "INFO", logger="api.services.eightfold_client"
        ):
            jobs = transform_to_job_listings("netflix", positions)

        assert len(jobs) == 5
        # Neither dedup log fires on the happy path.
        for r in caplog.records:
            msg = r.getMessage()
            assert "pagination-drift" not in msg
            assert "id collision" not in msg


# ----------------------------------------------------------------------------
# _parse_eightfold_epoch
# ----------------------------------------------------------------------------


class TestParseEightfoldEpoch:
    def test_none_returns_none(self):
        assert _parse_eightfold_epoch(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_eightfold_epoch("") is None

    def test_garbage_string_returns_none(self):
        assert _parse_eightfold_epoch("nope") is None

    def test_unix_seconds_int(self):
        # 2023-11-14T22:13:20+00:00
        result = _parse_eightfold_epoch(1_700_000_000)
        assert result is not None
        assert result.startswith("2023-11-14T")
        assert result.endswith("+00:00")

    def test_unix_seconds_string(self):
        result = _parse_eightfold_epoch("1700000000")
        assert result is not None
        assert result.startswith("2023-11-14T")

    def test_unix_seconds_float(self):
        result = _parse_eightfold_epoch(1_700_000_000.5)
        assert result is not None
        assert result.startswith("2023-11-14T")

    def test_milliseconds_defensive(self):
        """If Eightfold ever ships ms instead of s, we still parse it."""
        # 1_700_000_000_000 ms == 1_700_000_000 s
        result = _parse_eightfold_epoch(1_700_000_000_000)
        assert result is not None
        assert result.startswith("2023-11-14T")

    def test_zero_or_negative_returns_none(self):
        assert _parse_eightfold_epoch(0) is None
        assert _parse_eightfold_epoch(-1) is None

    @pytest.mark.parametrize("flag", [True, False])
    def test_a_boolean_is_not_a_timestamp(self, flag):
        """``t_create=true`` used to parse to ``1970-01-01``.

        ``isinstance(True, int)`` is True and ``float(True)`` is ``1.0``, so a flag
        that leaked into the date field — or a tenant answering the key with a
        presence boolean — sailed through ``float()`` as epoch 1. ``False`` was
        caught only by accident, by the ``<= 0`` guard sitting one line further down.

        It is not a value the caller can log and move past: it becomes a confidently
        wrong date on ``posted_on`` and, through ``effective_posted_date``, on
        ``first_seen_at`` — the column the product sorts and buckets by. The shared
        parser refuses bools for exactly this reason and never sees this one, because
        by then it has already been turned into a valid ISO string here.
        """
        assert _parse_eightfold_epoch(flag) is None

    def test_a_boolean_t_create_ends_up_null_and_logged_like_any_other_bad_value(
        self, caplog
    ):
        """End to end: NULL, not 1970, and ONE ERROR naming the value."""
        pos = _make_position(7, t_create=True)

        with caplog.at_level("ERROR", logger="api.services.eightfold_client"):
            jobs = transform_to_job_listings("netflix", [pos])

        assert len(jobs) == 1
        assert jobs[0].posted_on is None
        assert not jobs[0].first_seen_at.startswith("1970")
        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1, errors
        assert "t_create=True" in errors[0]


# ----------------------------------------------------------------------------
# U5c — an unparseable t_create is logged, not swallowed
# ----------------------------------------------------------------------------


class TestUnparseableTCreateLogging:
    """Eightfold was the only one of the six ATS clients that turned a bad
    provider date into NULL with nothing in the logs. Greenhouse and Workday
    both ERROR; a source-format change here would have silently zeroed our
    posted dates.

    The row must still be emitted with ``posted_on = None``, and the
    transform must not raise: this runs in the same task as the close sweep,
    so a bad date has to degrade its own row and nothing else.
    """

    def test_unparseable_t_create_logs_one_error_and_stores_none(self, caplog):
        pos = _make_position(1, t_create="not-a-timestamp")

        with caplog.at_level("ERROR", logger="api.services.eightfold_client"):
            jobs = transform_to_job_listings("netflix", [pos])

        assert len(jobs) == 1
        assert jobs[0].posted_on is None
        # Raw value is preserved for a later re-parse without a re-fetch.
        assert jobs[0].details["t_create_raw"] == "not-a-timestamp"

        errors = [
            r.getMessage() for r in caplog.records if r.levelname == "ERROR"
        ]
        assert len(errors) == 1, errors
        assert "data quality issue" in errors[0]
        assert "t_create" in errors[0]
        assert "not-a-timestamp" in errors[0]

    def test_missing_t_create_is_not_an_error(self, caplog):
        """No value is not a bad value — a board that publishes no date
        must not generate ERROR noise on every row of every tick."""
        pos = _make_position(2, t_create=None)

        with caplog.at_level("ERROR", logger="api.services.eightfold_client"):
            jobs = transform_to_job_listings("netflix", [pos])

        assert len(jobs) == 1
        assert jobs[0].posted_on is None
        assert [r for r in caplog.records if r.levelname == "ERROR"] == []

    def test_bad_date_does_not_take_down_the_batch(self, caplog):
        """Per-row degradation: the good rows keep their dates."""
        good_a = _make_position(10)
        bad = _make_position(11, t_create="garbage")
        good_b = _make_position(12)

        with caplog.at_level("ERROR", logger="api.services.eightfold_client"):
            jobs = transform_to_job_listings("netflix", [good_a, bad, good_b])

        assert [j.id for j in jobs] == ["10", "11", "12"]
        assert jobs[0].posted_on is not None
        assert jobs[1].posted_on is None
        assert jobs[2].posted_on is not None
        # And it never invents "now" for the failed row.
        assert jobs[1].posted_on != jobs[1].created_at
