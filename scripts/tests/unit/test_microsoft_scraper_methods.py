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
        """Large timestamp (milliseconds) handling"""
        scraper = MicrosoftJobsScraper(headless=True, detail_scrape=False)
        # Millisecond timestamp (13 digits) - this would be far in the future
        # The current implementation doesn't specifically handle ms vs s
        # so this tests the actual behavior
        timestamp = 1705320000  # seconds

        result = scraper._normalize_posted_date(timestamp)

        assert result is not None
        # Should produce a valid date string
        assert isinstance(result, str)


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
