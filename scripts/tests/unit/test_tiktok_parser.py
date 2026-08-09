"""Unit tests for the TikTok parser helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tiktok_jobs_scraper.parser import build_job_url, extract_job_id_from_url


class TestExtractJobIdFromUrl:
    def test_full_url(self):
        url = "https://lifeattiktok.com/search/7613184212766607621"
        assert extract_job_id_from_url(url) == "7613184212766607621"

    def test_path_only(self):
        assert extract_job_id_from_url("/search/123456") == "123456"

    def test_no_match(self):
        assert extract_job_id_from_url("https://lifeattiktok.com/about") is None

    def test_non_numeric(self):
        assert extract_job_id_from_url("/search/abc") is None

    def test_empty_and_none(self):
        assert extract_job_id_from_url("") is None
        assert extract_job_id_from_url(None) is None


class TestBuildJobUrl:
    def test_builds(self):
        assert build_job_url("123") == "https://lifeattiktok.com/search/123"

    def test_empty_returns_prefix(self):
        assert build_job_url("") == "https://lifeattiktok.com/search"
