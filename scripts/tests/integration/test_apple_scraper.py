"""
Integration tests for AppleJobsScraper transformation methods

Tests the data transformation, deduplication logic, and filter methods.
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.scraper import AppleJobsScraper
from shared.models import JobListing


@pytest.fixture
def sample_apple_job_data():
    """Sample job data from Apple scraper"""
    return {
        "id": "200640732-0836",
        "title": "Software Engineer, Machine Learning",
        "job_url": "https://jobs.apple.com/en-us/details/200640732-0836/software-engineer-ml",
        "team": "Machine Learning and AI",
        "location": "Cupertino, California, United States",
        "posted_date": "Dec 15, 2024",
        "company": "apple",
        "description": "Work on cutting-edge ML systems",
        "job_summary": "Join our ML team",
        "responsibilities": "Design and implement ML pipelines",
        "minimum_qualifications": ["BS in CS", "3+ years experience"],
        "preferred_qualifications": ["PhD preferred", "Published research"],
        "salary_range": "$175,000 - $295,000",
        "is_remote_eligible": False,
        "job_type": "Full-Time",
        "employment_type": "Individual Contributor",
        "team_names": ["Machine Learning", "AI Research"],
        "locations": [
            {"city": "Cupertino", "stateProvince": "California", "countryName": "United States"}
        ],
    }


class TestTransformToJobModel:
    """Tests for transform_to_job_model method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return AppleJobsScraper(headless=True, detail_scrape=False)

    def test_transform_to_job_model_complete(self, scraper, sample_apple_job_data):
        """Full job data transforms correctly"""
        result = scraper.transform_to_job_model(sample_apple_job_data)

        assert isinstance(result, JobListing)
        assert result.title == "Software Engineer, Machine Learning"
        assert result.company == "apple"
        assert result.location == "Cupertino, California, United States"
        assert result.source_id == "apple_scraper"
        assert result.status == "OPEN"
        assert result.id == "200640732-0836"

        # Check details
        assert "minimum_qualifications" in result.details
        assert result.details["salary_range"] == "$175,000 - $295,000"
        assert result.details["is_remote_eligible"] is False

    def test_transform_to_job_model_minimal(self, scraper):
        """Minimal data with defaults"""
        minimal_data = {
            "id": "123456",
            "title": "Simple Job",
            "job_url": "https://jobs.apple.com/en-us/details/123456/simple-job"
        }

        result = scraper.transform_to_job_model(minimal_data)

        assert result.title == "Simple Job"
        assert result.id == "123456"
        assert result.company == "apple"
        assert result.status == "OPEN"
        assert result.has_matched is False
        assert result.consecutive_misses == 0

    def test_transform_to_job_model_extracts_id_from_url(self, scraper):
        """Job ID extracted from URL when not in data"""
        data = {
            "title": "Test Job",
            "job_url": "https://jobs.apple.com/en-us/details/987654321/test-job-title"
        }

        result = scraper.transform_to_job_model(data)

        assert result.id == "987654321"

    def test_transform_to_job_model_unknown_id(self, scraper):
        """Handles missing/invalid URL"""
        data = {
            "title": "Test Job",
            "job_url": ""
        }

        result = scraper.transform_to_job_model(data)

        assert result.id == "unknown"

    def test_transform_to_job_model_preserves_raw_data(self, scraper, sample_apple_job_data):
        """Raw scraped data preserved in details"""
        result = scraper.transform_to_job_model(sample_apple_job_data)

        assert "raw" in result.details
        assert result.details["raw"]["title"] == sample_apple_job_data["title"]

    def test_transform_to_job_model_includes_apply_url(self, scraper, sample_apple_job_data):
        """Apply URL generated for job"""
        result = scraper.transform_to_job_model(sample_apple_job_data)

        assert "apply_url" in result.details
        assert "apply" in result.details["apply_url"]
        assert sample_apple_job_data["id"] in result.details["apply_url"]


class TestDeduplicateJobs:
    """Tests for deduplicate_jobs method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return AppleJobsScraper(headless=True, detail_scrape=False)

    def test_deduplicate_jobs_removes_duplicates(self, scraper):
        """Same ID appears once"""
        jobs = [
            {
                "id": "12345",
                "title": "Software Engineer",
                "job_url": "https://jobs.apple.com/en-us/details/12345/software-engineer",
                "location": "Cupertino"
            },
            {
                "id": "12345",  # Same job, same ID
                "title": "Software Engineer",
                "job_url": "https://jobs.apple.com/en-us/details/12345/software-engineer",
                "location": "Cupertino"
            },
            {
                "id": "67890",
                "title": "Data Scientist",
                "job_url": "https://jobs.apple.com/en-us/details/67890/data-scientist",
                "location": "Austin"
            }
        ]

        result = scraper.deduplicate_jobs(jobs)

        assert len(result) == 2
        ids = {j.id for j in result}
        assert ids == {"12345", "67890"}

    def test_deduplicate_jobs_preserves_order(self, scraper):
        """First occurrence kept"""
        jobs = [
            {
                "id": "12345",
                "title": "First Version",
                "job_url": "https://jobs.apple.com/en-us/details/12345/job",
                "location": "Location A"
            },
            {
                "id": "12345",  # Duplicate - should be ignored
                "title": "Second Version",
                "job_url": "https://jobs.apple.com/en-us/details/12345/job",
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

    def test_deduplicate_jobs_returns_job_listings(self, scraper):
        """Returns list of JobListing models"""
        jobs = [
            {
                "id": "12345",
                "title": "Software Engineer",
                "job_url": "https://jobs.apple.com/en-us/details/12345/software-engineer"
            }
        ]

        result = scraper.deduplicate_jobs(jobs)

        assert len(result) == 1
        assert isinstance(result[0], JobListing)


class TestBuildSearchUrl:
    """Tests for build_search_url method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return AppleJobsScraper(headless=True, detail_scrape=False)

    def test_build_search_url_page_1(self, scraper):
        """URL without page param for page 1"""
        url = scraper.build_search_url("", page_num=1)

        assert "page=" not in url
        assert "location=" in url

    def test_build_search_url_page_2(self, scraper):
        """URL includes page=2"""
        url = scraper.build_search_url("", page_num=2)

        assert "page=2" in url

    def test_build_search_url_includes_location(self, scraper):
        """URL includes location filter"""
        url = scraper.build_search_url("", page_num=1)

        assert "location=" in url


class TestFilterJob:
    """Tests for filter_job method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return AppleJobsScraper(headless=True, detail_scrape=False)

    def test_filter_job_includes_software(self, scraper):
        """'Software Engineer' passes filter"""
        assert scraper.filter_job("Software Engineer") is True
        assert scraper.filter_job("Senior Software Engineer") is True

    def test_filter_job_includes_data(self, scraper):
        """'Data' roles pass filter"""
        assert scraper.filter_job("Data Scientist") is True
        assert scraper.filter_job("Data Engineer") is True

    def test_filter_job_includes_machine_learning(self, scraper):
        """'Machine Learning' roles pass filter"""
        assert scraper.filter_job("Machine Learning Engineer") is True
        assert scraper.filter_job("ML Engineer") is True

    def test_filter_job_excludes_non_tech(self, scraper):
        """Non-tech roles filtered out"""
        # These depend on EXCLUDE_TITLE_KEYWORDS in config
        # Just test that something without include keywords fails
        assert scraper.filter_job("Retail Specialist") is False
        assert scraper.filter_job("Store Manager") is False


class TestGetCompanyName:
    """Tests for get_company_name method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return AppleJobsScraper(headless=True, detail_scrape=False)

    def test_get_company_name(self, scraper):
        """Returns 'apple'"""
        assert scraper.get_company_name() == "apple"


class TestGetSearchQueries:
    """Tests for get_search_queries method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return AppleJobsScraper(headless=True, detail_scrape=False)

    def test_get_search_queries(self, scraper):
        """Returns list with empty query (Apple uses location filter only)"""
        queries = scraper.get_search_queries()

        assert isinstance(queries, list)
        assert len(queries) == 1
        assert queries[0] == ""  # Apple uses empty query, filters by location


class TestScraperInit:
    """Tests for scraper initialization"""

    def test_init_with_defaults(self):
        """Scraper initializes with default values"""
        scraper = AppleJobsScraper()

        assert scraper.headless is True
        assert scraper.detail_scrape is False

    def test_init_with_custom_values(self):
        """Scraper accepts custom headless and detail_scrape"""
        scraper = AppleJobsScraper(headless=False, detail_scrape=True)

        assert scraper.headless is False
        assert scraper.detail_scrape is True
