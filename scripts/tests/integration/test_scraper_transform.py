"""
Integration tests for GoogleJobsScraper transformation methods

Tests the data transformation and deduplication logic.
"""

import pytest

from google_jobs_scraper.scraper import GoogleJobsScraper
from google_jobs_scraper.models import GoogleJob


class TestTransformToJobModel:
    """Tests for transform_to_job_model method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return GoogleJobsScraper(headless=True, detail_scrape=False)

    def test_transform_to_job_model_complete(self, scraper, sample_job_data_dict):
        """Full job data transforms correctly"""
        result = scraper.transform_to_job_model(sample_job_data_dict)

        assert isinstance(result, GoogleJob)
        assert result.title == "Software Engineer III, Cloud"
        assert result.company == "google"
        assert result.location == "Mountain View, CA, USA"
        assert result.source_id == "google_scraper"
        assert result.status == "OPEN"

        # Check details
        assert "minimum_qualifications" in result.details
        assert result.details["salary_range"] == "$185,000-$283,000"

    def test_transform_to_job_model_minimal(self, scraper):
        """Minimal data with defaults"""
        minimal_data = {
            "title": "Simple Job",
            "job_url": "https://www.google.com/about/careers/applications/jobs/results/12345-simple-job"
        }

        result = scraper.transform_to_job_model(minimal_data)

        assert result.title == "Simple Job"
        assert result.id == "12345"
        assert result.company == "google"  # Default
        assert result.status == "OPEN"
        assert result.has_matched is False
        assert result.consecutive_misses == 0

    def test_transform_to_job_model_extracts_id(self, scraper):
        """Job ID extracted from URL"""
        data = {
            "title": "Test Job",
            "job_url": "https://www.google.com/about/careers/applications/jobs/results/987654321098765432-test-job-title"
        }

        result = scraper.transform_to_job_model(data)

        assert result.id == "987654321098765432"

    def test_transform_to_job_model_unknown_id(self, scraper):
        """Handles missing/invalid URL"""
        data = {
            "title": "Test Job",
            "job_url": ""  # Empty URL
        }

        result = scraper.transform_to_job_model(data)

        assert result.id == "unknown"

    def test_transform_to_job_model_preserves_raw_data(self, scraper, sample_job_data_dict):
        """Raw scraped data preserved in details"""
        result = scraper.transform_to_job_model(sample_job_data_dict)

        assert "raw" in result.details
        assert result.details["raw"]["title"] == sample_job_data_dict["title"]


class TestDeduplicateJobs:
    """Tests for deduplicate_jobs method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return GoogleJobsScraper(headless=True, detail_scrape=False)

    def test_deduplicate_jobs_removes_duplicates(self, scraper):
        """Same URL appears once"""
        jobs = [
            {
                "title": "Software Engineer",
                "job_url": "https://www.google.com/about/careers/applications/jobs/results/12345-software-engineer",
                "location": "Mountain View"
            },
            {
                "title": "Software Engineer",  # Same job, same URL
                "job_url": "https://www.google.com/about/careers/applications/jobs/results/12345-software-engineer",
                "location": "Mountain View"
            },
            {
                "title": "Data Scientist",
                "job_url": "https://www.google.com/about/careers/applications/jobs/results/67890-data-scientist",
                "location": "New York"
            }
        ]

        result = scraper.deduplicate_jobs(jobs)

        assert len(result) == 2  # Only 2 unique jobs
        urls = {j.url for j in result}
        assert len(urls) == 2

    def test_deduplicate_jobs_preserves_order(self, scraper):
        """First occurrence kept"""
        jobs = [
            {
                "title": "First Version",
                "job_url": "https://www.google.com/about/careers/applications/jobs/results/12345-job",
                "location": "Location A"
            },
            {
                "title": "Second Version",  # Duplicate - should be ignored
                "job_url": "https://www.google.com/about/careers/applications/jobs/results/12345-job",
                "location": "Location B"
            }
        ]

        result = scraper.deduplicate_jobs(jobs)

        assert len(result) == 1
        assert result[0].title == "First Version"

    def test_deduplicate_jobs_empty_list(self, scraper):
        """Handles empty list"""
        result = scraper.deduplicate_jobs([])
        assert result == []

    def test_deduplicate_jobs_returns_google_jobs(self, scraper):
        """Returns list of GoogleJob models"""
        jobs = [
            {
                "title": "Software Engineer",
                "job_url": "https://www.google.com/about/careers/applications/jobs/results/12345-software-engineer"
            }
        ]

        result = scraper.deduplicate_jobs(jobs)

        assert len(result) == 1
        assert isinstance(result[0], GoogleJob)


class TestBuildSearchUrl:
    """Tests for build_search_url method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return GoogleJobsScraper(headless=True, detail_scrape=False)

    def test_build_search_url_page_1(self, scraper):
        """URL without page param for page 1"""
        url = scraper.build_search_url("software engineer", page_num=1)

        assert "software%20engineer" in url or "software+engineer" in url
        assert "page=" not in url

    def test_build_search_url_page_2(self, scraper):
        """URL includes page=2"""
        url = scraper.build_search_url("software engineer", page_num=2)

        assert "page=2" in url

    def test_build_search_url_includes_location(self, scraper):
        """URL includes location filter"""
        url = scraper.build_search_url("software engineer", page_num=1)

        assert "location=" in url


class TestFilterJob:
    """Tests for filter_job method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return GoogleJobsScraper(headless=True, detail_scrape=False)

    def test_filter_job_includes_software(self, scraper):
        """'Software Engineer' passes filter"""
        assert scraper.filter_job("Software Engineer") is True
        assert scraper.filter_job("Senior Software Engineer") is True

    def test_filter_job_includes_data(self, scraper):
        """'Data Scientist' passes filter"""
        assert scraper.filter_job("Data Scientist") is True
        assert scraper.filter_job("Data Engineer") is True

    def test_filter_job_excludes_recruiter(self, scraper):
        """'Technical Recruiter' filtered out"""
        assert scraper.filter_job("Technical Recruiter") is False
        assert scraper.filter_job("Software Recruiter") is False

    def test_filter_job_excludes_sales(self, scraper):
        """'Sales' roles filtered out"""
        assert scraper.filter_job("Sales Engineer") is False

    def test_filter_job_excludes_manager(self, scraper):
        """'Manager' roles filtered out only if explicitly in exclude list"""
        # "Engineering Manager" passes because it contains "engineer" (include)
        # and "manager" alone is not in exclude list (only "operations manager", "program manager" etc.)
        assert scraper.filter_job("Engineering Manager") is True
        # But specific manager types are excluded
        assert scraper.filter_job("Program Manager") is False
        assert scraper.filter_job("Product Manager") is False


class TestGetCompanyName:
    """Tests for get_company_name method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return GoogleJobsScraper(headless=True, detail_scrape=False)

    def test_get_company_name(self, scraper):
        """Returns 'google'"""
        assert scraper.get_company_name() == "google"


class TestGetSearchQueries:
    """Tests for get_search_queries method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return GoogleJobsScraper(headless=True, detail_scrape=False)

    def test_get_search_queries(self, scraper):
        """Returns list of search queries"""
        queries = scraper.get_search_queries()

        assert isinstance(queries, list)
        assert len(queries) > 0
        # Should contain at least 'software engineer'
        assert any("software" in q.lower() for q in queries)
