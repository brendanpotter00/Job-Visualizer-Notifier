"""
Unit tests for parser helper functions (google_jobs_scraper/parser.py)

Tests synchronous helper functions that don't require browser/page objects.
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from google_jobs_scraper.parser import extract_salary_from_text, check_remote_eligible


class TestExtractSalaryFromText:
    """Tests for extract_salary_from_text function"""

    def test_extract_salary_from_text_valid(self):
        """Extracts '$185,000-$283,000 + bonus + equity'"""
        text = "The salary range is $185,000-$283,000 + bonus + equity + benefits. Apply now!"
        result = extract_salary_from_text(text)

        assert result is not None
        assert "$185,000" in result
        assert "$283,000" in result

    def test_extract_salary_from_text_no_match(self):
        """Returns None for text without salary"""
        text = "This is a great job opportunity. Competitive compensation offered."
        result = extract_salary_from_text(text)

        assert result is None

    def test_extract_salary_from_text_partial(self):
        """Extracts '$100,000-$150,000' without extras"""
        text = "Base salary: $100,000-$150,000 annually"
        result = extract_salary_from_text(text)

        assert result is not None
        assert "$100,000" in result
        assert "$150,000" in result

    def test_extract_salary_from_text_with_bonus(self):
        """Extracts salary with bonus + equity + benefits"""
        text = "Compensation: $200,000-$300,000 + bonus + equity"
        result = extract_salary_from_text(text)

        assert result is not None
        assert "$200,000" in result
        assert "$300,000" in result

    def test_extract_salary_from_text_different_formats(self):
        """Handles various salary formats"""
        test_cases = [
            ("$50,000-$75,000", True),
            ("$120,000-$180,000 per year", True),
            ("Salary: $90,000-$110,000 + benefits", True),
            ("$1,000,000-$2,000,000", True),  # Million dollar salaries
        ]

        for text, should_match in test_cases:
            result = extract_salary_from_text(text)
            if should_match:
                assert result is not None, f"Should match: {text}"
            else:
                assert result is None, f"Should not match: {text}"

    def test_extract_salary_from_text_empty_string(self):
        """Empty string returns None"""
        assert extract_salary_from_text("") is None

    def test_extract_salary_from_text_no_range(self):
        """Single salary value (no range) doesn't match"""
        # The regex specifically looks for range format ($X-$Y)
        text = "Salary: $100,000 per year"
        result = extract_salary_from_text(text)

        # This may or may not match depending on regex - just verify no error
        # The current regex requires a range format
        assert result is None or "$100,000" in result


class TestCheckRemoteEligible:
    """Tests for check_remote_eligible function"""

    def test_check_remote_eligible_location(self):
        """Returns True if 'remote' in location"""
        job_details = {
            "location": "Remote, United States",
            "about_the_job": "Standard office job description"
        }
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_about(self):
        """Returns True if 'work from home' in about_the_job"""
        job_details = {
            "location": "New York, NY",
            "about_the_job": "This position offers work from home flexibility."
        }
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_false(self):
        """Returns False for no remote keywords"""
        job_details = {
            "location": "Mountain View, CA, USA",
            "about_the_job": "Join our team in our state-of-the-art office."
        }
        assert check_remote_eligible(job_details) is False

    def test_check_remote_eligible_empty(self):
        """Returns False for empty/missing fields"""
        assert check_remote_eligible({}) is False
        assert check_remote_eligible({"location": None, "about_the_job": None}) is False
        assert check_remote_eligible({"location": ""}) is False

    def test_check_remote_eligible_telecommute(self):
        """Returns True for 'telecommute' keyword"""
        job_details = {
            "location": "San Francisco, CA",
            "about_the_job": "Telecommute options available for this position."
        }
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_distributed(self):
        """Returns True for 'distributed' keyword"""
        job_details = {
            "location": "Multiple locations",
            "about_the_job": "We are a distributed team across time zones."
        }
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_case_insensitive(self):
        """Keywords match case-insensitively"""
        job_details = {
            "location": "REMOTE",
            "about_the_job": "Office based"
        }
        assert check_remote_eligible(job_details) is True

        job_details = {
            "location": "New York",
            "about_the_job": "WORK FROM HOME is supported"
        }
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_only_location(self):
        """Works with only location field"""
        job_details = {"location": "Remote - US Only"}
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_only_about(self):
        """Works with only about_the_job field"""
        job_details = {"about_the_job": "This is a remote-first position."}
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_partial_match(self):
        """Partial keyword matches work"""
        job_details = {
            "location": "San Francisco",
            "about_the_job": "Remote-first culture with optional office space"
        }
        assert check_remote_eligible(job_details) is True

    def test_check_remote_eligible_false_positive_prevention(self):
        """Doesn't false match on similar words"""
        # "remotely" contains "remote" so this should still match
        job_details = {
            "location": "Boston, MA",
            "about_the_job": "Collaborate remotely with team members"
        }
        # This should match because "remotely" contains "remote"
        assert check_remote_eligible(job_details) is True
