"""Unit tests for TikTokJobsScraper's synchronous helper methods."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
from tiktok_jobs_scraper.config import (
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    SEARCH_QUERIES,
)
from tiktok_jobs_scraper.scraper import TikTokJobsScraper


class TestIdentity:
    def test_company_name(self, tiktok_scraper):
        assert tiktok_scraper.get_company_name() == "tiktok"

    def test_source_id(self, tiktok_scraper):
        assert tiktok_scraper.SOURCE_ID == SourceId.TIKTOK == "tiktok_scraper"

    def test_search_queries(self, tiktok_scraper):
        assert tiktok_scraper.get_search_queries() == SEARCH_QUERIES == ["software engineer"]

    def test_defaults(self):
        s = TikTokJobsScraper()
        assert s.headless is True
        assert s.detail_scrape is False


class TestBuildSearchUrl:
    def test_encodes_query(self, tiktok_scraper):
        url = tiktok_scraper.build_search_url("software engineer", 1)
        assert "keyword=software+engineer" in url
        assert url.startswith("https://lifeattiktok.com/search")
        assert " " not in url


class TestRandomDelay:
    def test_callable_with_no_arguments(self, tiktok_scraper):
        with patch("asyncio.sleep", new=AsyncMock()) as slept:
            asyncio.run(tiktok_scraper._random_delay())
        slept.assert_awaited_once()

    def test_within_bounds(self, tiktok_scraper):
        with patch("asyncio.sleep", new=AsyncMock()) as slept:
            asyncio.run(tiktok_scraper._random_delay())
        assert REQUEST_DELAY_MIN <= slept.await_args[0][0] <= REQUEST_DELAY_MAX

    def test_varies(self, tiktok_scraper):
        with patch("asyncio.sleep", new=AsyncMock()) as slept:
            for _ in range(10):
                asyncio.run(tiktok_scraper._random_delay())
            seen = {c[0][0] for c in slept.await_args_list}
        assert len(seen) > 1


class TestFilterJob:
    @pytest.mark.parametrize("title", [
        "Software Engineer, TikTok AIGC Agentic Workflow",
        "Senior Backend Engineer - TikTok Shop",
        "Machine Learning Engineer, Recommendation",
        "Data Scientist, Monetization",
        "Site Reliability Engineer",
        "Security Engineer, Privacy",
    ])
    def test_keeps_technical(self, tiktok_scraper, title):
        assert tiktok_scraper.filter_job(title) is True

    @pytest.mark.parametrize("title", [
        "Technical Recruiter, R&D",
        "Account Executive, TikTok Shop",
        "Human Resources Business Partner",
        "Content Moderator, Trust and Safety",
    ])
    def test_drops_non_technical(self, tiktok_scraper, title):
        assert tiktok_scraper.filter_job(title) is False

    def test_threat_is_not_matched_by_hr(self, tiktok_scraper):
        """Regression: bare substring "HR" matches T-h-r-eat."""
        assert tiktok_scraper.filter_job("Software Engineer, Threat Intelligence") is True

    def test_empty_title(self, tiktok_scraper):
        assert tiktok_scraper.filter_job("") is False
        assert tiktok_scraper.filter_job(None) is False


class TestFilterLocation:
    def test_keeps_us(self, tiktok_scraper):
        assert tiktok_scraper.filter_location(
            "San Jose, California, United States of America"
        ) is True

    @pytest.mark.parametrize("loc", [
        "Singapore, Singapore, Singapore",
        "Tokyo, Japan",
        "London, England, United Kingdom",
    ])
    def test_drops_non_us(self, tiktok_scraper, loc):
        assert tiktok_scraper.filter_location(loc) is False

    def test_missing_location_is_dropped(self, tiktok_scraper):
        assert tiktok_scraper.filter_location(None) is False
        assert tiktok_scraper.filter_location("") is False

    def test_case_insensitive(self, tiktok_scraper):
        assert tiktok_scraper.filter_location("austin, texas, UNITED STATES of america") is True


class TestDeriveExperienceLevel:
    def test_recruit_type_intern_wins(self, tiktok_scraper):
        assert tiktok_scraper.derive_experience_level(
            "Software Engineer", {"recruit_type": "Intern"}
        ) == "Intern"

    @pytest.mark.parametrize("title,expected", [
        ("Senior Software Engineer", "Senior"),
        ("Tech Lead Software Engineer", "Senior"),
        ("Principal Engineer", "Principal"),
        ("Head of Engineering", "Principal"),
        ("Graduate Software Engineer", "Entry"),
        ("Software Engineer Internship - 2026", "Intern"),
        ("Software Engineer", None),
    ])
    def test_from_title(self, tiktok_scraper, title, expected):
        assert tiktok_scraper.derive_experience_level(title, {"recruit_type": "Regular"}) == expected

    def test_missing_recruit_type_is_safe(self, tiktok_scraper):
        assert tiktok_scraper.derive_experience_level("Software Engineer", {}) is None


class TestDeriveIsRemoteEligible:
    def test_remote_in_title(self, tiktok_scraper):
        assert tiktok_scraper.derive_is_remote_eligible("SWE (Remote)", None) is True

    def test_plain(self, tiktok_scraper):
        assert tiktok_scraper.derive_is_remote_eligible("SWE", "San Jose, California") is False

    def test_none_safe(self, tiktok_scraper):
        assert tiktok_scraper.derive_is_remote_eligible(None, None) is False


class TestExtractJobDetailsIsInert:
    def test_returns_empty_and_touches_nothing(self, tiktok_scraper):
        page = MagicMock()
        result = asyncio.run(tiktok_scraper.extract_job_details(page, "https://x/search/1"))
        assert result == {}
        page.goto.assert_not_called()
        page.evaluate.assert_not_called()
