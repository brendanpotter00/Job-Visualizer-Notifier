"""
Integration tests for MicrosoftJobsScraper transformation methods

Tests the data transformation, deduplication logic, and filter methods.
"""

import pytest

from scripts.microsoft_jobs_scraper.scraper import MicrosoftJobsScraper
from shared.models import JobListing

# Fixtures: microsoft_scraper, sample_microsoft_job_data from conftest.py


class TestTransformToJobModel:
    """Tests for transform_to_job_model method"""

    def test_transform_to_job_model_complete(self, microsoft_scraper, sample_microsoft_job_data):
        """Full job data transforms correctly"""
        result = microsoft_scraper.transform_to_job_model(sample_microsoft_job_data)

        assert isinstance(result, JobListing)
        assert result.title == "Software Engineer II"
        assert result.company == "microsoft"
        assert result.location == "Redmond, WA, USA"
        assert result.source_id == "microsoft_scraper"
        assert result.status == "OPEN"
        assert result.id == "1970393556642428"

        # Check details
        assert "minimum_qualifications" in result.details
        assert result.details["salary_range"] == "$130,000 - $190,000"
        assert result.details["work_site"] == "Hybrid"
        assert result.details["job_number"] == "200016306"

    def test_transform_to_job_model_minimal(self, microsoft_scraper):
        """Minimal data with defaults"""
        minimal_data = {
            "id": "1234567890",
            "title": "Simple Job",
            "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890"
        }

        result = microsoft_scraper.transform_to_job_model(minimal_data)

        assert result.title == "Simple Job"
        assert result.id == "1234567890"
        assert result.company == "microsoft"
        assert result.status == "OPEN"
        assert result.has_matched is False
        assert result.consecutive_misses == 0

    def test_transform_to_job_model_extracts_id_from_url(self, microsoft_scraper):
        """Job ID extracted from URL when not in data"""
        data = {
            "title": "Test Job",
            "job_url": "https://apply.careers.microsoft.com/careers?position_id=9876543210&domain=microsoft.com"
        }

        result = microsoft_scraper.transform_to_job_model(data)

        assert result.id == "9876543210"

    def test_transform_to_job_model_unknown_id(self, microsoft_scraper):
        """Handles missing/invalid URL"""
        data = {
            "title": "Test Job",
            "job_url": ""
        }

        result = microsoft_scraper.transform_to_job_model(data)

        assert result.id == "unknown"

    def test_transform_to_job_model_preserves_raw_data(self, microsoft_scraper, sample_microsoft_job_data):
        """Raw scraped data preserved in details"""
        result = microsoft_scraper.transform_to_job_model(sample_microsoft_job_data)

        assert "raw" in result.details
        assert result.details["raw"]["title"] == sample_microsoft_job_data["title"]

    def test_transform_to_job_model_includes_apply_url(self, microsoft_scraper, sample_microsoft_job_data):
        """Apply URL generated for job"""
        result = microsoft_scraper.transform_to_job_model(sample_microsoft_job_data)

        assert "apply_url" in result.details
        assert "apply" in result.details["apply_url"]
        assert sample_microsoft_job_data["id"] in result.details["apply_url"]

    def test_transform_to_job_model_handles_posted_on(self, microsoft_scraper, sample_microsoft_job_data):
        """Posted on date is captured"""
        result = microsoft_scraper.transform_to_job_model(sample_microsoft_job_data)

        assert result.posted_on == "2024-12-15"


class TestDeduplicateJobs:
    """Tests for deduplicate_jobs method"""

    def test_deduplicate_jobs_removes_duplicates(self, microsoft_scraper):
        """Same ID appears once"""
        jobs = [
            {
                "id": "1234567890",
                "title": "Software Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890",
                "location": "Redmond"
            },
            {
                "id": "1234567890",  # Same job, same ID
                "title": "Software Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890",
                "location": "Redmond"
            },
            {
                "id": "0987654321",
                "title": "Data Scientist",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=0987654321",
                "location": "Seattle"
            }
        ]

        result = microsoft_scraper.deduplicate_jobs(jobs)

        assert len(result) == 2
        ids = {j.id for j in result}
        assert ids == {"1234567890", "0987654321"}

    def test_deduplicate_jobs_preserves_order(self, microsoft_scraper):
        """First occurrence kept"""
        jobs = [
            {
                "id": "1234567890",
                "title": "First Version",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890",
                "location": "Location A"
            },
            {
                "id": "1234567890",  # Duplicate - should be ignored
                "title": "Second Version",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890",
                "location": "Location B"
            }
        ]

        result = microsoft_scraper.deduplicate_jobs(jobs)

        assert len(result) == 1
        assert result[0].title == "First Version"

    def test_deduplicate_jobs_empty_list(self, microsoft_scraper):
        """Handles empty list"""
        result = microsoft_scraper.deduplicate_jobs([])
        assert result == []

    def test_deduplicate_jobs_returns_job_listings(self, microsoft_scraper):
        """Returns list of JobListing models"""
        jobs = [
            {
                "id": "1234567890",
                "title": "Software Engineer",
                "job_url": "https://apply.careers.microsoft.com/careers?position_id=1234567890"
            }
        ]

        result = microsoft_scraper.deduplicate_jobs(jobs)

        assert len(result) == 1
        assert isinstance(result[0], JobListing)


class TestBuildSearchUrl:
    """Tests for build_search_url method"""

    def test_build_search_url_page_1(self, microsoft_scraper):
        """URL with start=0 for page 1"""
        url = microsoft_scraper.build_search_url("software engineer", page_num=1)

        assert "start=0" in url
        assert "software engineer" in url.lower() or "software%20engineer" in url.lower()

    def test_build_search_url_page_2(self, microsoft_scraper):
        """URL includes start=10 for page 2 (10 jobs per page)"""
        url = microsoft_scraper.build_search_url("software engineer", page_num=2)

        assert "start=10" in url

    def test_build_search_url_page_3(self, microsoft_scraper):
        """URL includes start=20 for page 3"""
        url = microsoft_scraper.build_search_url("software engineer", page_num=3)

        assert "start=20" in url

    def test_build_search_url_includes_location(self, microsoft_scraper):
        """URL includes location filter"""
        url = microsoft_scraper.build_search_url("data scientist", page_num=1)

        assert "location=" in url

    def test_build_search_url_includes_domain(self, microsoft_scraper):
        """URL includes domain parameter"""
        url = microsoft_scraper.build_search_url("ml engineer", page_num=1)

        assert "domain=microsoft.com" in url


class TestFilterJob:
    """Tests for filter_job method"""

    def test_filter_job_includes_software(self, microsoft_scraper):
        """'Software Engineer' passes filter"""
        assert microsoft_scraper.filter_job("Software Engineer") is True
        assert microsoft_scraper.filter_job("Senior Software Engineer") is True

    def test_filter_job_includes_data(self, microsoft_scraper):
        """'Data' roles pass filter"""
        assert microsoft_scraper.filter_job("Data Scientist") is True
        assert microsoft_scraper.filter_job("Data Engineer") is True

    def test_filter_job_includes_machine_learning(self, microsoft_scraper):
        """'Machine Learning' roles pass filter"""
        # Note: 'Machine Learning' keyword was removed, but 'ML' is still there
        assert microsoft_scraper.filter_job("ML Engineer") is True

    def test_filter_job_includes_cloud(self, microsoft_scraper):
        """'Cloud' roles pass filter"""
        assert microsoft_scraper.filter_job("Cloud Engineer") is True
        assert microsoft_scraper.filter_job("Cloud Developer") is True

    def test_filter_job_includes_security(self, microsoft_scraper):
        """'Security' roles pass filter"""
        assert microsoft_scraper.filter_job("Security Engineer") is True

    def test_filter_job_includes_research(self, microsoft_scraper):
        """'Research' roles pass filter"""
        assert microsoft_scraper.filter_job("Research Scientist") is True
        assert microsoft_scraper.filter_job("Research Engineer") is True

    def test_filter_job_excludes_non_tech(self, microsoft_scraper):
        """Non-tech roles filtered out"""
        assert microsoft_scraper.filter_job("Account Executive") is False
        assert microsoft_scraper.filter_job("Sales Representative") is False
        assert microsoft_scraper.filter_job("Retail Store Manager") is False


class TestGetCompanyName:
    """Tests for get_company_name method"""

    def test_get_company_name(self, microsoft_scraper):
        """Returns 'microsoft'"""
        assert microsoft_scraper.get_company_name() == "microsoft"


class TestGetSearchQueries:
    """Tests for get_search_queries method"""

    def test_get_search_queries(self, microsoft_scraper):
        """Returns list with search queries"""
        queries = microsoft_scraper.get_search_queries()

        assert isinstance(queries, list)
        assert len(queries) >= 1
        assert "software engineer" in queries


class TestScraperInit:
    """Tests for scraper initialization"""

    def test_init_with_defaults(self):
        """Scraper initializes with default values"""
        scraper = MicrosoftJobsScraper()

        assert scraper.headless is True
        assert scraper.detail_scrape is False

    def test_init_with_custom_values(self):
        """Scraper accepts custom headless and detail_scrape"""
        scraper = MicrosoftJobsScraper(headless=False, detail_scrape=True)

        assert scraper.headless is False
        assert scraper.detail_scrape is True
