"""
Unit tests for AmazonJobsScraper's synchronous helper methods.

The title-filter regressions here are live-verified: reusing Microsoft's
keyword lists verbatim dropped 31 real Amazon SWE jobs, 4 of them because the
bare substring "HR" matches "T-h-r-eat".
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amazon_jobs_scraper.config import REQUEST_DELAY_MAX, REQUEST_DELAY_MIN, SEARCH_QUERIES
from amazon_jobs_scraper.scraper import AmazonJobsScraper
from shared.constants import SourceId


class TestIdentity:
    def test_company_name(self, amazon_scraper):
        assert amazon_scraper.get_company_name() == "amazon"

    def test_source_id(self, amazon_scraper):
        assert amazon_scraper.SOURCE_ID == SourceId.AMAZON == "amazon_scraper"

    def test_search_queries(self, amazon_scraper):
        assert amazon_scraper.get_search_queries() == SEARCH_QUERIES
        assert amazon_scraper.get_search_queries() == ["software engineer"]

    def test_defaults(self):
        s = AmazonJobsScraper()
        assert s.headless is True
        assert s.detail_scrape is False

    def test_custom_init(self):
        s = AmazonJobsScraper(headless=False, detail_scrape=True)
        assert s.headless is False
        assert s.detail_scrape is True


class TestBuildSearchUrl:
    def test_page_one_offset_zero(self, amazon_scraper):
        url = amazon_scraper.build_search_url("software engineer", 1)
        assert "offset=0" in url
        assert url.startswith("https://www.amazon.jobs/en/search")

    def test_page_three_offset(self, amazon_scraper):
        assert "offset=200" in amazon_scraper.build_search_url("software engineer", 3)

    def test_query_is_encoded(self, amazon_scraper):
        url = amazon_scraper.build_search_url("software engineer", 1)
        assert "base_query=software+engineer" in url
        assert " " not in url

    def test_country_filter_present(self, amazon_scraper):
        assert "country=USA" in amazon_scraper.build_search_url("x", 1)


class TestRandomDelay:
    """The zero-arg override is the JVN convention — the base takes two args."""

    def test_callable_with_no_arguments(self, amazon_scraper):
        with patch("asyncio.sleep", new=AsyncMock()) as slept:
            asyncio.run(amazon_scraper._random_delay())
        slept.assert_awaited_once()

    def test_delay_within_configured_bounds(self, amazon_scraper):
        with patch("asyncio.sleep", new=AsyncMock()) as slept:
            asyncio.run(amazon_scraper._random_delay())
        delay = slept.await_args[0][0]
        assert REQUEST_DELAY_MIN <= delay <= REQUEST_DELAY_MAX

    def test_delay_varies(self, amazon_scraper):
        seen = set()
        with patch("asyncio.sleep", new=AsyncMock()) as slept:
            for _ in range(10):
                asyncio.run(amazon_scraper._random_delay())
            seen = {c[0][0] for c in slept.await_args_list}
        assert len(seen) > 1, "delay should be jittered, not constant"


class TestFilterJob:
    @pytest.mark.parametrize(
        "title",
        [
            "Software Development Engineer II",
            "SDE II, AWS Marketplace",
            "Sr. SDE, EC2 Nitro Networking",
            "Applied Scientist III",
            "IT App Dev Engr II",
            "Machine Learning Engineer",
            "Data Engineer, Alexa",
            "Cloud Support Engineer",
            "Security Engineer",
        ],
    )
    def test_keeps_technical_titles(self, amazon_scraper, title):
        assert amazon_scraper.filter_job(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Technical Recruiter",
            "Account Executive",
            "Sales Representative, AWS",
            "Human Resources Business Partner",
        ],
    )
    def test_drops_non_technical_titles(self, amazon_scraper, title):
        assert amazon_scraper.filter_job(title) is False

    def test_threat_is_not_matched_by_hr(self, amazon_scraper):
        """Regression: bare substring "HR" matches T-h-r-eat.

        This live title was dropped by a substring-based exclude list.
        """
        title = "Software Development Engineer II - Threat Intelligence Systems"
        assert amazon_scraper.filter_job(title) is True

    def test_sales_insights_engineering_role_is_kept(self, amazon_scraper):
        """A software role that merely mentions the word "Sales"."""
        title = "Software Dev Engineer II, Sales Insights and Data Science"
        assert amazon_scraper.filter_job(title) is True

    def test_empty_title(self, amazon_scraper):
        assert amazon_scraper.filter_job("") is False
        assert amazon_scraper.filter_job(None) is False

    def test_exclude_beats_include(self, amazon_scraper):
        assert amazon_scraper.filter_job("Software Engineering Recruiter") is False

    def test_team_name_cannot_veto_a_real_engineering_role(self, amazon_scraper):
        """Regression, live title: EXCLUDE must read the role, not the org.

        Amazon titles are "<Role>, <Team>". Matching the whole string dropped a
        genuine Principal SWE req because its *team* name says "Recruiting".
        """
        title = (
            "Principal Engineer, Amazon | Multiple Locations, USA, "
            "Global Specialty Recruiting Team"
        )
        assert amazon_scraper.filter_job(title) is True

    def test_recruiting_still_excluded_when_it_is_the_role(self, amazon_scraper):
        """The narrowing must not defang the exclude list itself."""
        assert amazon_scraper.filter_job("Technical Recruiter, AWS") is False
        assert amazon_scraper.filter_job("Recruiting Manager, Amazon Devices") is False

    def test_empty_exclude_list_excludes_nothing(self, amazon_scraper):
        """An empty alternation `(?:)` matches the empty string everywhere.

        Emptying the list to "turn off excludes" would otherwise reject nearly
        the whole board — every title containing punctuation or a digit.
        """
        import re as _re

        from amazon_jobs_scraper import scraper as scraper_module

        with patch.object(scraper_module, "_EXCLUDE_RE", _re.compile(r"(?!)")):
            assert amazon_scraper.filter_job("Software Development Engineer, EC2") is True
            assert amazon_scraper.filter_job("Sr. Software Engineer") is True
            assert amazon_scraper.filter_job("SDE II - Amazon Robotics") is True


class TestDeriveExperienceLevel:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Software Development Engineer Intern", "Intern"),
            ("SDE Internship - Summer 2026", "Intern"),
            ("University Graduate Software Engineer", "Entry"),
            ("Principal Engineer, AWS", "Principal"),
            ("Distinguished Engineer", "Principal"),
            ("Sr. Software Development Engineer", "Senior"),
            ("Senior Applied Scientist", "Senior"),
            ("Software Development Engineer III", "Senior"),
            ("Software Development Engineer II", "Mid"),
            ("Software Development Engineer", None),
        ],
    )
    def test_from_title(self, amazon_scraper, title, expected):
        assert amazon_scraper.derive_experience_level(title, {}) == expected

    def test_null_structured_flags_do_not_crash(self, amazon_scraper):
        """Amazon returns null for these on 100% of live rows."""
        data = {"is_intern": None, "university_job": None, "is_manager": None}
        assert amazon_scraper.derive_experience_level("Software Engineer", data) is None

    def test_structured_flag_wins_when_present(self, amazon_scraper):
        assert amazon_scraper.derive_experience_level(
            "Software Development Engineer", {"is_intern": True}
        ) == "Intern"

    def test_ai_does_not_match_bare_i(self, amazon_scraper):
        """"AI" must not be read as the roman numeral I."""
        assert amazon_scraper.derive_experience_level("AI Research Engineer", {}) is None

    def test_integration_and_test_is_not_entry_level(self, amazon_scraper):
        """Live regression: "I&T" is Integration & Test, not roman numeral I."""
        title = "Software I&T Engineer, Amazon Leo for Government"
        assert amazon_scraper.derive_experience_level(title, {}) != "Entry"


class TestDeriveIsRemoteEligible:
    def test_remote_in_title(self, amazon_scraper):
        assert amazon_scraper.derive_is_remote_eligible("SDE II (Remote)", None) is True

    def test_virtual_in_title(self, amazon_scraper):
        assert amazon_scraper.derive_is_remote_eligible("Virtual Support Engineer", None) is True

    def test_plain_title_is_false(self, amazon_scraper):
        assert amazon_scraper.derive_is_remote_eligible("SDE II", "desc") is False

    def test_none_description_is_safe(self, amazon_scraper):
        assert amazon_scraper.derive_is_remote_eligible("SDE II", None) is False


class TestExtractJobDetailsIsInert:
    """Amazon never detail-fetches; the ABC method must be a no-op."""

    def test_returns_empty_dict_and_touches_nothing(self, amazon_scraper):
        page = MagicMock()
        result = asyncio.run(amazon_scraper.extract_job_details(page, "https://x/en/jobs/1/y"))
        assert result == {}
        page.goto.assert_not_called()
        page.evaluate.assert_not_called()
