"""Integration tests for TikTokJobsScraper transformation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
from shared.models import JobListing


class TestTransformToJobModel:
    def test_complete_card(self, tiktok_scraper, sample_tiktok_job_data):
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)
        assert isinstance(job, JobListing)
        assert job.id == "7613184212766607621"
        assert job.company == "tiktok"
        assert job.source_id == SourceId.TIKTOK
        assert job.url == "https://lifeattiktok.com/search/7613184212766607621"
        assert job.location == "San Jose, California, United States of America"
        assert job.status == "OPEN"
        assert job.closed_on is None

    def test_posted_on_is_always_none(self, tiktok_scraper, sample_tiktok_job_data):
        """TikTok's payload carries no date field; first_seen_at is the signal."""
        assert tiktok_scraper.transform_to_job_model(sample_tiktok_job_data).posted_on is None

    def test_timestamps_converge_because_tiktok_publishes_no_date(
        self, tiktok_scraper, sample_tiktok_job_data
    ):
        """The three timestamps agree here for a REASON, not by definition.

        ``first_seen_at`` is the EFFECTIVE POSTED DATE (POSTED-DATE-PLAN §2) —
        the board's own date when it has one, first sight otherwise. TikTok's
        payload carries no date field at all, so first sight is all three. The
        assertion on ``posted_on`` is what stops this from being a tautology: if
        TikTok's payload ever grows a date and the scraper starts reading it,
        that line fails first and names the reason.
        """
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)

        assert job.posted_on is None, (
            "TikTok now publishes a date — first_seen_at must follow it, and this "
            "test's premise no longer holds"
        )
        assert job.created_at == job.first_seen_at == job.last_seen_at

    def test_description_lands_where_backend_reads_it(self, tiktok_scraper, sample_tiktok_job_data):
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)
        assert job.details["description"] == sample_tiktok_job_data["description"]

    def test_denormalised_column_keys_present(self, tiktok_scraper, sample_tiktok_job_data):
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)
        assert "experience_level" in job.details
        assert "is_remote_eligible" in job.details
        assert job.details["is_remote_eligible"] is False

    def test_department_preserved(self, tiktok_scraper, sample_tiktok_job_data):
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)
        assert job.details["department"] == "R&D / Backend"

    def test_raw_preserved(self, tiktok_scraper, sample_tiktok_job_data):
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)
        assert job.details["raw"] == sample_tiktok_job_data

    def test_minimal_card(self, tiktok_scraper):
        job = tiktok_scraper.transform_to_job_model({"id": "1", "title": "SWE"})
        assert job.id == "1"
        assert job.location is None

    def test_id_falls_back_to_url(self, tiktok_scraper):
        job = tiktok_scraper.transform_to_job_model(
            {"title": "SWE", "job_url": "https://lifeattiktok.com/search/999888777"}
        )
        assert job.id == "999888777"

    def test_id_unknown_when_absent(self, tiktok_scraper):
        assert tiktok_scraper.transform_to_job_model({"title": "SWE"}).id == "unknown"

    def test_intern_recruit_type_sets_experience(self, tiktok_scraper, sample_tiktok_job_data):
        sample_tiktok_job_data["recruit_type"] = "Intern"
        job = tiktok_scraper.transform_to_job_model(sample_tiktok_job_data)
        assert job.details["experience_level"] == "Intern"


class TestDeduplicateJobs:
    def test_removes_duplicates(self, tiktok_scraper, sample_tiktok_job_data):
        out = tiktok_scraper.deduplicate_jobs(
            [sample_tiktok_job_data, dict(sample_tiktok_job_data)]
        )
        assert len(out) == 1

    def test_preserves_order(self, tiktok_scraper, sample_tiktok_job_data):
        b = dict(sample_tiktok_job_data, id="222")
        c = dict(sample_tiktok_job_data, id="333")
        out = tiktok_scraper.deduplicate_jobs([sample_tiktok_job_data, b, c])
        assert [j.id for j in out] == ["7613184212766607621", "222", "333"]

    def test_returns_models(self, tiktok_scraper, sample_tiktok_job_data):
        assert all(isinstance(j, JobListing)
                   for j in tiktok_scraper.deduplicate_jobs([sample_tiktok_job_data]))

    def test_skips_falsy_ids(self, tiktok_scraper, sample_tiktok_job_data):
        out = tiktok_scraper.deduplicate_jobs([{"id": "", "title": "x"}, sample_tiktok_job_data])
        assert len(out) == 1

    def test_empty(self, tiktok_scraper):
        assert tiktok_scraper.deduplicate_jobs([]) == []
