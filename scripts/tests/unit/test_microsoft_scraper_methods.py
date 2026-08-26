"""
Unit tests for MicrosoftJobsScraper helper methods

Tests _normalize_posted_date(), _random_delay(), and other utility methods.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from microsoft_jobs_scraper.scraper import MicrosoftJobsScraper


class TestNormalizePostedDate:
    """Tests for _normalize_posted_date method"""

    def test_normalize_none_returns_none(self):
        """None input returns None"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        result = scraper._normalize_posted_date(None)

        assert result is None

    def test_normalize_string_passthrough(self):
        """String input returned as-is"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        result = scraper._normalize_posted_date("2024-12-15")

        assert result == "2024-12-15"

    def test_normalize_string_iso_format(self):
        """ISO string format preserved"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        result = scraper._normalize_posted_date("2024-12-15T10:30:00Z")

        assert result == "2024-12-15T10:30:00Z"

    def test_normalize_int_timestamp(self):
        """Unix seconds timestamp converted to ISO format"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        # Unix timestamp for 2024-01-15 12:00:00 UTC
        timestamp = 1705320000

        result = scraper._normalize_posted_date(timestamp)

        assert result is not None
        assert "2024-01-15" in result
        # Should be ISO format
        assert "T" in result

    def test_normalize_float_timestamp(self):
        """Float timestamp converted to ISO format"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        # Float timestamp
        timestamp = 1705320000.5

        result = scraper._normalize_posted_date(timestamp)

        assert result is not None
        assert "2024-01-15" in result

    def test_normalize_millisecond_timestamp(self):
        """A 13-digit millisecond timestamp lands in the right year.

        This test was named for milliseconds but passed 1705320000 —
        SECONDS, 10 digits. It therefore asserted nothing about the ms
        path and stayed green while `_normalize_posted_date` read
        milliseconds as seconds and produced year-58,000 dates. Pass
        actual milliseconds and assert the resulting year.
        """
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        # 1705320000000 ms == 1705320000 s == 2024-01-15 12:00:00 UTC.
        result = scraper._normalize_posted_date(1705320000000)

        assert result is not None
        assert result.startswith("2024-01-15"), result

    def test_epoch_seconds_and_milliseconds_agree(self):
        """The live prod value from the plan: `1787617881` (2026). Both
        scales must land on the same instant — not 1970, not year 58,000.
        """
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        seconds = scraper._normalize_posted_date(1787617881)
        millis = scraper._normalize_posted_date(1787617881000)

        assert seconds is not None and millis is not None
        assert seconds.startswith("2026-"), seconds
        assert millis.startswith("2026-"), millis
        assert seconds == millis

    def test_empty_string_returns_none(self):
        """`_get_first_of` defaults to `""`, not None, so `""` is the
        normal shape for "Microsoft published no date". It used to be
        `str()`-ed through into a TIMESTAMPTZ, which failed the INSERT —
        the batch then retried row-by-row and dropped exactly those rows.
        NULL is the only safe answer.
        """
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        assert scraper._normalize_posted_date("") is None
        assert scraper._normalize_posted_date("   ") is None

    def test_humanized_string_returns_none(self):
        """A relative bucket is not a date (POSTED-DATE-PLAN.md §3), and
        Postgres cannot store it either. NULL, never a synthesized date.
        """
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        for humanized in ("2 days ago", "Posted 30+ Days Ago", "about 12 hours"):
            assert scraper._normalize_posted_date(humanized) is None, humanized

    def test_bad_value_never_becomes_now(self):
        """The invariant that matters: a failed parse degrades this row to
        NULL. It must never fall back to the current time, which would put
        a stale job on today's bar in the graph.
        """
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        assert scraper._normalize_posted_date("garbage") is None
        assert scraper._normalize_posted_date({"not": "a date"}) is None
        assert scraper._normalize_posted_date([]) is None

    def test_transform_stores_null_rather_than_failing_the_batch(self):
        """End-to-end through `transform_to_job_model`: the real shape a
        dateless Microsoft row arrives in is `posted_date == ""`.
        """
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        job = scraper.transform_to_job_model({
            "id": "1970393556642428",
            "title": "Software Engineer",
            "job_url": "https://jobs.careers.microsoft.com/global/en/job/1970393556642428",
            "posted_on": "",
            "posted_date": "",
        })

        assert job.posted_on is None

    def test_transform_stores_a_real_epoch_date(self):
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        job = scraper.transform_to_job_model({
            "id": "1970393556642428",
            "title": "Software Engineer",
            "job_url": "https://jobs.careers.microsoft.com/global/en/job/1970393556642428",
            "posted_on": "",
            "posted_date": 1787617881,
        })

        assert job.posted_on is not None
        assert job.posted_on.startswith("2026-"), job.posted_on


class TestRandomDelay:
    """Tests for _random_delay method"""

    @pytest.mark.asyncio
    async def test_random_delay_in_config_range(self):
        """Delay is within configured range (2.0 - 5.0 seconds)"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            await scraper._random_delay()

            mock_sleep.assert_called_once()
            delay = mock_sleep.call_args[0][0]
            # From config.py: REQUEST_DELAY_MIN = 2.0, REQUEST_DELAY_MAX = 5.0
            assert 2.0 <= delay <= 5.0

    @pytest.mark.asyncio
    async def test_random_delay_calls_sleep(self):
        """asyncio.sleep is called"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            await scraper._random_delay()

            mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_random_delay_varies(self):
        """Delay values vary (not constant)"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        delays = []

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            # Call multiple times
            for _ in range(10):
                await scraper._random_delay()
                delays.append(mock_sleep.call_args[0][0])

        # At least some variation in delays (not all the same)
        # This test may occasionally fail if random generates same value,
        # but 10 calls should produce variation
        assert len(set(delays)) > 1


class TestGetCompanyName:
    """Tests for get_company_name method"""

    def test_get_company_name_returns_microsoft(self):
        """Returns 'microsoft' as company identifier"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        result = scraper.get_company_name()

        assert result == "microsoft"


class TestBuildSearchUrl:
    """Tests for build_search_url method"""

    def test_build_search_url_includes_query(self):
        """URL includes search query"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        url = scraper.build_search_url("software engineer", page_num=1)

        assert "software" in url.lower()
        assert "engineer" in url.lower()

    def test_build_search_url_calculates_start(self):
        """Start parameter calculated correctly from page number"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        url_page_1 = scraper.build_search_url("test", page_num=1)
        url_page_2 = scraper.build_search_url("test", page_num=2)
        url_page_3 = scraper.build_search_url("test", page_num=3)

        assert "start=0" in url_page_1
        assert "start=10" in url_page_2
        assert "start=20" in url_page_3


class TestFilterJob:
    """Tests for filter_job method"""

    def test_filter_job_includes_software_engineer(self):
        """Software Engineer titles pass filter"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        assert scraper.filter_job("Software Engineer") is True
        assert scraper.filter_job("Senior Software Engineer") is True
        assert scraper.filter_job("Software Engineer II") is True

    def test_filter_job_includes_developer(self):
        """Developer titles pass filter"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        assert scraper.filter_job("Full Stack Developer") is True
        assert scraper.filter_job("Senior Developer") is True

    def test_filter_job_excludes_non_tech(self):
        """Non-tech titles are filtered out"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        assert scraper.filter_job("Account Executive") is False
        assert scraper.filter_job("Sales Manager") is False
        assert scraper.filter_job("Retail Store Associate") is False

    def test_filter_job_case_insensitive(self):
        """Filter is case insensitive"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)

        assert scraper.filter_job("SOFTWARE ENGINEER") is True
        assert scraper.filter_job("software engineer") is True
        assert scraper.filter_job("Software ENGINEER") is True
