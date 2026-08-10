"""Unit tests for the Amazon parser helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amazon_jobs_scraper.parser import build_job_url, extract_job_id_from_url


class TestExtractJobIdFromUrl:
    def test_full_url(self):
        url = "https://www.amazon.jobs/en/jobs/10496449/software-development-engineer"
        assert extract_job_id_from_url(url) == "10496449"

    def test_path_only(self):
        assert extract_job_id_from_url("/en/jobs/10496449/sde") == "10496449"

    def test_no_slug(self):
        assert extract_job_id_from_url("https://www.amazon.jobs/en/jobs/10496449") == "10496449"

    def test_no_match(self):
        assert extract_job_id_from_url("https://www.amazon.jobs/en/search") is None

    def test_non_numeric_segment(self):
        assert extract_job_id_from_url("/en/jobs/abc/sde") is None

    def test_empty_and_none(self):
        assert extract_job_id_from_url("") is None
        assert extract_job_id_from_url(None) is None


class TestBuildJobUrl:
    def test_relative(self):
        assert build_job_url("/en/jobs/1/x") == "https://www.amazon.jobs/en/jobs/1/x"

    def test_absolute_passthrough(self):
        url = "https://www.amazon.jobs/en/jobs/1/x"
        assert build_job_url(url) == url

    def test_empty_returns_origin(self):
        assert build_job_url("") == "https://www.amazon.jobs"
