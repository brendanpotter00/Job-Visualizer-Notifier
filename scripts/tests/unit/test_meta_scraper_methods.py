"""Unit tests for MetaJobsScraper's synchronous helper methods."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
from shared.models import JobListing
from shared.posted_date import effective_posted_date
from meta_jobs_scraper.config import LIST_URL
from meta_jobs_scraper.scraper import MetaJobsScraper


def _card(job_id="j1", title="Software Engineer, Infra", location="Menlo Park, CA"):
    return {
        "id": job_id,
        "title": title,
        "location": location,
        "department": "Infrastructure — Data Platform",
        "job_url": f"https://www.metacareers.com/profile/job_details/{job_id}",
        "company": "meta",
        "raw": {"id": job_id, "title": title},
    }


class TestIdentity:
    def test_company_name(self, meta_scraper):
        assert meta_scraper.get_company_name() == "meta"

    def test_source_id(self, meta_scraper):
        assert meta_scraper.SOURCE_ID == SourceId.META == "meta_scraper"

    def test_search_queries(self, meta_scraper):
        assert meta_scraper.get_search_queries() == ["all"]

    def test_defaults(self):
        s = MetaJobsScraper()
        assert s.headless is True
        assert s.detail_scrape is False


class TestBuildSearchUrl:
    def test_returns_jobsearch_url(self, meta_scraper):
        url = meta_scraper.build_search_url("ignored", 3)
        assert url == LIST_URL
        assert url == "https://www.metacareers.com/jobsearch"


class TestTransformToJobModel:
    def test_core_fields(self, meta_scraper):
        job = meta_scraper.transform_to_job_model(_card())
        assert isinstance(job, JobListing)
        assert job.id == "j1"
        assert job.title == "Software Engineer, Infra"
        assert job.company == "meta"
        assert job.location == "Menlo Park, CA"
        assert job.url == "https://www.metacareers.com/profile/job_details/j1"
        assert job.source_id == SourceId.META
        assert job.status == "OPEN"

    def test_posted_on_is_none(self, meta_scraper):
        """Meta's list query carries no posted date."""
        assert meta_scraper.transform_to_job_model(_card()).posted_on is None

    def test_first_seen_at_is_effective_posted_date(self, meta_scraper):
        job = meta_scraper.transform_to_job_model(_card())
        # posted_on is None ⇒ effective date is first sight (created_at)
        assert job.first_seen_at == job.created_at
        assert job.first_seen_at == effective_posted_date(None, job.created_at)

    def test_details_shape(self, meta_scraper):
        job = meta_scraper.transform_to_job_model(_card())
        assert job.details["description"] is None
        assert job.details["department"] == "Infrastructure — Data Platform"
        assert job.details["apply_url"] == "https://www.metacareers.com/profile/job_details/j1"
        assert job.details["raw"] == {"id": "j1", "title": "Software Engineer, Infra"}

    def test_details_scraped_false(self, meta_scraper):
        assert meta_scraper.transform_to_job_model(_card()).details_scraped is False


class TestDeduplicateJobs:
    def test_dedupes_by_id_returns_joblistings(self, meta_scraper):
        cards = [_card("j1"), _card("j1"), _card("j2")]
        jobs = meta_scraper.deduplicate_jobs(cards)
        assert all(isinstance(j, JobListing) for j in jobs)
        assert [j.id for j in jobs] == ["j1", "j2"]

    def test_skips_blank_ids(self, meta_scraper):
        jobs = meta_scraper.deduplicate_jobs([{"id": "", "title": "x"}, _card("j9")])
        assert [j.id for j in jobs] == ["j9"]


class TestExtractJobDetailsIsInert:
    def test_returns_empty_and_touches_nothing(self, meta_scraper):
        page = MagicMock()
        result = asyncio.run(
            meta_scraper.extract_job_details(page, "https://www.metacareers.com/profile/job_details/1")
        )
        assert result == {}
        page.goto.assert_not_called()
        page.evaluate.assert_not_called()

    def test_extract_job_cards_is_thin(self, meta_scraper):
        page = MagicMock()
        result = asyncio.run(meta_scraper.extract_job_cards(page))
        assert result == []
        page.goto.assert_not_called()


class TestFilterJob:
    @pytest.mark.parametrize("title", [
        "Software Engineer, Infrastructure",
        "Senior Backend Engineer, Instagram",
        "Machine Learning Engineer, GenAI",
        "Data Scientist, Ads",
        "Site Reliability Engineer",
        "Security Engineer, Privacy",
    ])
    def test_keeps_technical(self, meta_scraper, title):
        assert meta_scraper.filter_job(title) is True

    @pytest.mark.parametrize("title", [
        "Technical Recruiter",
        "Account Executive, Reality Labs",
        "Human Resources Business Partner",
        "Content Moderator, Trust and Safety",
    ])
    def test_drops_non_technical(self, meta_scraper, title):
        assert meta_scraper.filter_job(title) is False

    def test_threat_is_not_matched_by_hr(self, meta_scraper):
        """Regression: bare substring "HR" matches T-h-r-eat."""
        assert meta_scraper.filter_job("Software Engineer, Threat Intelligence") is True

    def test_empty_title(self, meta_scraper):
        assert meta_scraper.filter_job("") is False
        assert meta_scraper.filter_job(None) is False


class TestFilterLocation:
    """The US filter against Meta's REAL ``City, ST`` location format.

    Meta writes ``Menlo Park, CA`` (never ``…, United States``), joins multiple
    locations with ``, ``, marks US remote as ``Remote, US``, and spells non-US
    countries out in full. The old ``"United States"`` substring matched none of
    these and silently dropped every job — these cases pin the real format.
    """

    @pytest.mark.parametrize("loc", [
        "Menlo Park, CA",                       # single City, ST
        "New York, NY",
        "Washington, DC",                       # DC
        "Lebanon, IN",                          # Indiana (a 2-letter that is also a word)
        "Remote, US",                           # US remote
        "Menlo Park, CA, New York, NY",         # multiple US locations joined
        "London, UK, Menlo Park, CA",           # mixed US + non-US counts as US
        "Menlo Park, Florida",                  # spelled-out state name
        "Austin, TX, United States",            # superset: still accepts the old form
    ])
    def test_keeps_us(self, meta_scraper, loc):
        assert meta_scraper.filter_location(loc) is True

    @pytest.mark.parametrize("loc", [
        "London, UK",
        "Singapore",
        "Dublin, Ireland",
        "Bangalore, India",                     # India spelled out, NOT the code IN
        "Sao Paulo, Brazil",
        "Remote, UK",                           # non-US remote is dropped
        "Tbilisi, Georgia",                     # the COUNTRY Georgia, not the US state
    ])
    def test_drops_non_us(self, meta_scraper, loc):
        assert meta_scraper.filter_location(loc) is False

    def test_missing_location_is_dropped(self, meta_scraper):
        assert meta_scraper.filter_location(None) is False
        assert meta_scraper.filter_location("") is False

    def test_case_insensitive(self, meta_scraper):
        assert meta_scraper.filter_location("AUSTIN, TX") is True
        assert meta_scraper.filter_location("menlo park, ca") is True
