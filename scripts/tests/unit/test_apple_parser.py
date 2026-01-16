"""
Unit tests for Apple Jobs parser functions (apple_jobs_scraper/parser.py)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.parser import extract_job_id_from_url


class TestExtractJobIdFromUrl:
    """Tests for extract_job_id_from_url function"""

    def test_extract_job_id_with_location_code(self):
        """Extracts ID with location suffix (e.g., 200640732-0836)"""
        url = "/en-us/details/200640732-0836/software-qa-engineer?team=SFTWR"
        assert extract_job_id_from_url(url) == "200640732-0836"

    def test_extract_job_id_without_location_code(self):
        """Extracts ID without location suffix"""
        url = "/en-us/details/114438158/us-specialist-full-time?team=APPST"
        assert extract_job_id_from_url(url) == "114438158"

    def test_extract_job_id_full_url(self):
        """Works with full URL"""
        url = "https://jobs.apple.com/en-us/details/200640732-0836/software-qa-engineer?team=SFTWR"
        assert extract_job_id_from_url(url) == "200640732-0836"

    def test_extract_job_id_various_ids(self):
        """Works with different job IDs"""
        test_cases = [
            ("/en-us/details/200630959-0836/ai-ml-engineer?team=HRDWR", "200630959-0836"),
            ("/en-us/details/200640907-3956/sr-program-manager?team=OPMFG", "200640907-3956"),
            ("/en-us/details/200634538-0836/aiml-ui-engineer?team=MLAI", "200634538-0836"),
            ("/en-us/details/200634538-3337/aiml-ui-engineer?team=MLAI", "200634538-3337"),
        ]
        for url, expected_id in test_cases:
            assert extract_job_id_from_url(url) == expected_id

    def test_extract_job_id_empty_url(self):
        """Returns None for empty URL"""
        assert extract_job_id_from_url("") is None

    def test_extract_job_id_no_match(self):
        """Returns None if no /details/ in URL"""
        assert extract_job_id_from_url("https://jobs.apple.com/en-us/search") is None
        assert extract_job_id_from_url("https://apple.com/careers") is None
        assert extract_job_id_from_url("/en-us/search?location=usa") is None

    def test_extract_job_id_malformed_url(self):
        """Returns None for malformed URL"""
        assert extract_job_id_from_url("not-a-url") is None
        assert extract_job_id_from_url("/en-us/details/") is None  # No ID after /details/


class TestJobIdLocationVariants:
    """Tests for handling same job with different locations"""

    def test_same_position_different_locations(self):
        """Same position ID with different location codes are distinct"""
        # Same position (200634538) but different locations (Cupertino vs Seattle)
        cupertino_url = "/en-us/details/200634538-0836/aiml-ui-engineer?team=MLAI"
        seattle_url = "/en-us/details/200634538-3337/aiml-ui-engineer?team=MLAI"

        cupertino_id = extract_job_id_from_url(cupertino_url)
        seattle_id = extract_job_id_from_url(seattle_url)

        # IDs should be different (includes location code)
        assert cupertino_id == "200634538-0836"
        assert seattle_id == "200634538-3337"
        assert cupertino_id != seattle_id

    def test_position_id_can_be_extracted(self):
        """Position ID (base) can be extracted from full job ID"""
        full_id = "200634538-0836"
        # Position ID is the part before the hyphen
        position_id = full_id.split("-")[0] if "-" in full_id else full_id
        assert position_id == "200634538"
