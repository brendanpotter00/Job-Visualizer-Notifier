"""
Integration tests for TikTokJobsScraper transformation methods

Tests the data transformation, deduplication logic, and filter methods.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tiktok_jobs_scraper.scraper import TikTokJobsScraper
from shared.models import JobListing


@pytest.fixture
def sample_tiktok_job_data():
    """Sample job data from TikTok scraper"""
    return {
        "id": "7579201004205164805",
        "title": "Software Engineer - USDS",
        "job_url": "https://lifeattiktok.com/search/7579201004205164805",
        "location": "San Jose",
        "category": "Technology",
        "employment_type": "Regular",
        "company": "tiktok",
        "responsibilities": "Our team of US Tech Services...",
        "minimum_qualifications": ["BS/MS degree in Computer Science", "3+ years experience"],
        "preferred_qualifications": ["Deep knowledge of distributed systems", "Published research"],
        "salary_range": "$118657 - $259200",
        "job_code": "A16898B",
        "about": "TikTok is the leading platform for short-form video...",
        "why_join": "Join us to make an impact...",
    }


class TestTransformToJobModel:
    """Tests for transform_to_job_model method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return TikTokJobsScraper(headless=True, detail_scrape=False)

    def test_transform_to_job_model_complete(self, scraper, sample_tiktok_job_data):
        """Full job data transforms correctly"""
        result = scraper.transform_to_job_model(sample_tiktok_job_data)

        assert isinstance(result, JobListing)
        assert result.title == "Software Engineer - USDS"
        assert result.company == "tiktok"
        assert result.location == "San Jose"
        assert result.source_id == "tiktok_scraper"
        assert result.status == "OPEN"
        assert result.id == "7579201004205164805"

        # Check details
        assert "minimum_qualifications" in result.details
        assert result.details["salary_range"] == "$118657 - $259200"
        assert result.details["job_code"] == "A16898B"
        assert result.details["category"] == "Technology"

    def test_transform_to_job_model_minimal(self, scraper):
        """Minimal data with defaults"""
        minimal_data = {
            "id": "123456",
            "title": "Simple Job",
            "job_url": "https://lifeattiktok.com/search/123456"
        }

        result = scraper.transform_to_job_model(minimal_data)

        assert result.title == "Simple Job"
        assert result.id == "123456"
        assert result.company == "tiktok"
        assert result.status == "OPEN"
        assert result.has_matched is False
        assert result.consecutive_misses == 0

    def test_transform_to_job_model_extracts_id_from_url(self, scraper):
        """Job ID extracted from URL when not in data"""
        data = {
            "title": "Test Job",
            "job_url": "https://lifeattiktok.com/search/9876543210"
        }

        result = scraper.transform_to_job_model(data)

        assert result.id == "9876543210"

    def test_transform_to_job_model_unknown_id(self, scraper):
        """Handles missing/invalid URL"""
        data = {
            "title": "Test Job",
            "job_url": ""
        }

        result = scraper.transform_to_job_model(data)

        assert result.id == "unknown"

    def test_transform_to_job_model_preserves_raw_data(self, scraper, sample_tiktok_job_data):
        """Raw scraped data preserved in details"""
        result = scraper.transform_to_job_model(sample_tiktok_job_data)

        assert "raw" in result.details
        assert result.details["raw"]["title"] == sample_tiktok_job_data["title"]

    def test_transform_to_job_model_includes_apply_url(self, scraper, sample_tiktok_job_data):
        """Apply URL generated for job"""
        result = scraper.transform_to_job_model(sample_tiktok_job_data)

        assert "apply_url" in result.details
        assert "careers.tiktok.com" in result.details["apply_url"]
        assert sample_tiktok_job_data["id"] in result.details["apply_url"]


class TestDeduplicateJobs:
    """Tests for deduplicate_jobs method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return TikTokJobsScraper(headless=True, detail_scrape=False)

    def test_deduplicate_jobs_removes_duplicates(self, scraper):
        """Same ID appears once"""
        jobs = [
            {
                "id": "12345",
                "title": "Software Engineer",
                "job_url": "https://lifeattiktok.com/search/12345",
                "location": "San Jose"
            },
            {
                "id": "12345",  # Same job, same ID
                "title": "Software Engineer",
                "job_url": "https://lifeattiktok.com/search/12345",
                "location": "San Jose"
            },
            {
                "id": "67890",
                "title": "Data Scientist",
                "job_url": "https://lifeattiktok.com/search/67890",
                "location": "Seattle"
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
                "job_url": "https://lifeattiktok.com/search/12345",
                "location": "Location A"
            },
            {
                "id": "12345",  # Duplicate - should be ignored
                "title": "Second Version",
                "job_url": "https://lifeattiktok.com/search/12345",
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
                "job_url": "https://lifeattiktok.com/search/12345"
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
        return TikTokJobsScraper(headless=True, detail_scrape=False)

    def test_build_search_url_page_1(self, scraper):
        """URL without offset for page 1"""
        url = scraper.build_search_url("software engineer", page_num=1)

        assert "offset=" not in url
        assert "keyword=software" in url
        assert "limit=12" in url

    def test_build_search_url_page_2(self, scraper):
        """URL includes offset=12 for page 2"""
        url = scraper.build_search_url("software engineer", page_num=2)

        assert "offset=12" in url

    def test_build_search_url_page_3(self, scraper):
        """URL includes offset=24 for page 3"""
        url = scraper.build_search_url("software engineer", page_num=3)

        assert "offset=24" in url

    def test_build_search_url_encodes_query(self, scraper):
        """URL encodes search query"""
        url = scraper.build_search_url("software engineer", page_num=1)

        assert "software%20engineer" in url or "software+engineer" in url


class TestFilterJob:
    """Tests for filter_job method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return TikTokJobsScraper(headless=True, detail_scrape=False)

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

    def test_filter_job_includes_usds(self, scraper):
        """USDS roles pass filter (if they contain software keywords)"""
        assert scraper.filter_job("Software Engineer - USDS") is True

    def test_filter_job_excludes_non_tech(self, scraper):
        """Non-tech roles filtered out"""
        assert scraper.filter_job("Content Moderator") is False
        assert scraper.filter_job("Trust and Safety Manager") is False
        assert scraper.filter_job("Policy Specialist") is False

    def test_filter_job_excludes_recruiter(self, scraper):
        """Recruiter roles filtered out"""
        assert scraper.filter_job("Technical Recruiter") is False

    def test_filter_job_excludes_manager(self, scraper):
        """Manager roles filtered out"""
        assert scraper.filter_job("Engineering Manager") is False


class TestGetCompanyName:
    """Tests for get_company_name method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return TikTokJobsScraper(headless=True, detail_scrape=False)

    def test_get_company_name(self, scraper):
        """Returns 'tiktok'"""
        assert scraper.get_company_name() == "tiktok"


class TestGetSearchQueries:
    """Tests for get_search_queries method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return TikTokJobsScraper(headless=True, detail_scrape=False)

    def test_get_search_queries(self, scraper):
        """Returns list with search query"""
        queries = scraper.get_search_queries()

        assert isinstance(queries, list)
        assert len(queries) >= 1
        assert "software engineer" in queries


class TestScraperInit:
    """Tests for scraper initialization"""

    def test_init_with_defaults(self):
        """Scraper initializes with default values"""
        scraper = TikTokJobsScraper()

        assert scraper.headless is True
        assert scraper.detail_scrape is False

    def test_init_with_custom_values(self):
        """Scraper accepts custom headless and detail_scrape"""
        scraper = TikTokJobsScraper(headless=False, detail_scrape=True)

        assert scraper.headless is False
        assert scraper.detail_scrape is True


class TestMaxJobsEarlyTermination:
    """Tests for max_jobs pagination safeguards"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance without browser"""
        return TikTokJobsScraper(headless=True, detail_scrape=False)

    @pytest.mark.asyncio
    async def test_stops_after_consecutive_empty_pages(self, scraper):
        """Scraper stops after 5 consecutive pages with no matching jobs"""
        # Create mock page
        mock_page = AsyncMock()

        # Mock context.new_page to return our mock page
        scraper.context = MagicMock()
        scraper.context.new_page = AsyncMock(return_value=mock_page)

        # Mock navigate_to_page to do nothing
        scraper.navigate_to_page = AsyncMock()

        # Each page returns 12 jobs that don't pass filter (no software keywords)
        non_matching_jobs = [
            {
                "id": f"job_{i}",
                "title": "Content Moderator",  # Excluded keyword
                "job_url": f"https://lifeattiktok.com/search/job_{i}",
            }
            for i in range(12)
        ]

        # extract_job_cards will return non-matching jobs every time
        call_count = 0

        async def mock_extract_job_cards(page):
            nonlocal call_count
            call_count += 1
            # Return jobs with incrementing IDs to avoid dedup
            return [
                {
                    "id": f"job_{call_count}_{i}",
                    "title": "Content Moderator",
                    "job_url": f"https://lifeattiktok.com/search/job_{call_count}_{i}",
                }
                for i in range(12)
            ]

        scraper.extract_job_cards = mock_extract_job_cards

        # Mock check_has_next_page to always return True
        with patch(
            "tiktok_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            with patch(
                "tiktok_jobs_scraper.scraper.extract_total_jobs_count",
                AsyncMock(return_value=1000),
            ):
                result = await scraper.scrape_query("software engineer", max_jobs=5)

        # Should stop after 5 consecutive pages with no matches
        assert call_count == 5
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_stops_after_seeing_too_many_raw_jobs(self, scraper):
        """Scraper stops after seeing 10x max_jobs raw jobs without enough matches"""
        mock_page = AsyncMock()
        scraper.context = MagicMock()
        scraper.context.new_page = AsyncMock(return_value=mock_page)
        scraper.navigate_to_page = AsyncMock()

        call_count = 0

        async def mock_extract_job_cards(page):
            nonlocal call_count
            call_count += 1
            # Return mix of matching and non-matching jobs
            # 1 matching + 11 non-matching per page
            jobs = [
                {
                    "id": f"match_{call_count}",
                    "title": "Software Engineer",  # Matches filter
                    "job_url": f"https://lifeattiktok.com/search/match_{call_count}",
                }
            ]
            for i in range(11):
                jobs.append(
                    {
                        "id": f"nomatch_{call_count}_{i}",
                        "title": "Content Moderator",  # Excluded
                        "job_url": f"https://lifeattiktok.com/search/nomatch_{call_count}_{i}",
                    }
                )
            return jobs

        scraper.extract_job_cards = mock_extract_job_cards

        with patch(
            "tiktok_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            with patch(
                "tiktok_jobs_scraper.scraper.extract_total_jobs_count",
                AsyncMock(return_value=1000),
            ):
                # max_jobs=5, so should stop after seeing 50 raw jobs
                # That's ceil(50/12) = ~4-5 pages
                result = await scraper.scrape_query("software engineer", max_jobs=5)

        # Should have collected some matching jobs before stopping
        # With max_jobs=5 and 10x multiplier, stops at 50 raw jobs = ~4 pages
        # Each page has 1 match, so 4-5 matches expected
        assert len(result) >= 4
        assert call_count <= 6  # Should stop before scraping forever

    @pytest.mark.asyncio
    async def test_resets_consecutive_counter_on_match(self, scraper):
        """Consecutive empty pages counter resets when a matching job is found"""
        mock_page = AsyncMock()
        scraper.context = MagicMock()
        scraper.context.new_page = AsyncMock(return_value=mock_page)
        scraper.navigate_to_page = AsyncMock()

        call_count = 0

        async def mock_extract_job_cards(page):
            nonlocal call_count
            call_count += 1
            # Pattern: 2 empty pages, then 1 match, repeat
            # Pages 1-2: no matches, Page 3: match
            # Pages 4-5: no matches, Page 6: match
            # Pages 7-8: no matches, Page 9: match
            # This never hits 5 consecutive empty pages
            # Return only 1 job per page to avoid 10x safeguard
            if call_count % 3 == 0:  # Pages 3, 6, 9, 12...
                return [
                    {
                        "id": f"match_{call_count}",
                        "title": "Software Engineer",
                        "job_url": f"https://lifeattiktok.com/search/match_{call_count}",
                    }
                ]
            return [
                {
                    "id": f"nomatch_{call_count}",
                    "title": "Content Moderator",
                    "job_url": f"https://lifeattiktok.com/search/nomatch_{call_count}",
                }
            ]

        scraper.extract_job_cards = mock_extract_job_cards

        with patch(
            "tiktok_jobs_scraper.scraper.check_has_next_page",
            AsyncMock(return_value=True),
        ):
            with patch(
                "tiktok_jobs_scraper.scraper.extract_total_jobs_count",
                AsyncMock(return_value=1000),
            ):
                result = await scraper.scrape_query("software engineer", max_jobs=3)

        # Should get 3 matches (pages 3, 6, 9) and stop due to max_jobs limit
        assert len(result) == 3
        assert call_count == 9  # Should have scraped exactly 9 pages
