"""
Integration tests for AmazonJobsScraper transformation.

``transform_to_job_model`` is the canonical data contract — the e2e integrity
harness runs every live card through it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
from shared.models import JobListing


class TestTransformToJobModel:
    def test_complete_card(self, amazon_scraper, sample_amazon_job_data):
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)

        assert isinstance(job, JobListing)
        assert job.id == "10496449"
        assert job.title == "Software Development Engineer II"
        assert job.company == "amazon"
        assert job.source_id == SourceId.AMAZON
        assert job.url.startswith("https://www.amazon.jobs/en/jobs/")
        assert job.location == "Seattle, Washington, USA"
        assert job.status == "OPEN"
        assert job.closed_on is None
        assert job.consecutive_misses == 0

    def test_posted_on_passthrough(self, amazon_scraper, sample_amazon_job_data):
        """The card's posted_date is already normalised by the api_client."""
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)
        assert job.posted_on == "2026-08-08"

    def test_timestamps_are_consistent(self, amazon_scraper, sample_amazon_job_data):
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)
        assert job.created_at == job.first_seen_at == job.last_seen_at

    def test_description_lands_where_the_backend_reads_it(
        self, amazon_scraper, sample_amazon_job_data
    ):
        """The enrichment monitor COALESCEs details->>'description'."""
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)
        assert job.details["description"] == sample_amazon_job_data["description"]

    def test_denormalised_column_keys_present(self, amazon_scraper, sample_amazon_job_data):
        """shared/database.py reads these two details keys by name."""
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)
        assert "experience_level" in job.details
        assert "is_remote_eligible" in job.details
        assert job.details["experience_level"] == "Mid"
        assert job.details["is_remote_eligible"] is False

    def test_raw_card_preserved(self, amazon_scraper, sample_amazon_job_data):
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)
        assert job.details["raw"] == sample_amazon_job_data

    def test_minimal_card(self, amazon_scraper):
        job = amazon_scraper.transform_to_job_model({"id": "1", "title": "SDE"})
        assert job.id == "1"
        assert job.location is None
        assert job.posted_on is None

    def test_id_falls_back_to_url(self, amazon_scraper):
        job = amazon_scraper.transform_to_job_model(
            {"title": "SDE", "job_url": "https://www.amazon.jobs/en/jobs/987654/sde"}
        )
        assert job.id == "987654"

    def test_missing_id_raises_rather_than_fabricating_one(self, amazon_scraper):
        """A placeholder id collides on the composite PK (source_id, id).

        Two id-less cards sharing "unknown" collapse into a single row that
        flip-flops between two different real jobs and publishes the result.
        BatchWriter.add_job isolates a raising transform, so one bad card is
        counted and skipped without killing the run.
        """
        with pytest.raises(ValueError, match="refusing to fabricate"):
            amazon_scraper.transform_to_job_model({"title": "SDE"})

    def test_apply_url_carried(self, amazon_scraper, sample_amazon_job_data):
        job = amazon_scraper.transform_to_job_model(sample_amazon_job_data)
        assert job.details["apply_url"] == sample_amazon_job_data["apply_url"]


class TestDeduplicateJobs:
    def test_removes_duplicates(self, amazon_scraper, sample_amazon_job_data):
        dupe = dict(sample_amazon_job_data)
        out = amazon_scraper.deduplicate_jobs([sample_amazon_job_data, dupe])
        assert len(out) == 1

    def test_preserves_order(self, amazon_scraper, sample_amazon_job_data):
        second = dict(sample_amazon_job_data, id="222", title="Second")
        third = dict(sample_amazon_job_data, id="333", title="Third")
        out = amazon_scraper.deduplicate_jobs([sample_amazon_job_data, second, third])
        assert [j.id for j in out] == ["10496449", "222", "333"]

    def test_returns_job_listing_instances(self, amazon_scraper, sample_amazon_job_data):
        out = amazon_scraper.deduplicate_jobs([sample_amazon_job_data])
        assert all(isinstance(j, JobListing) for j in out)

    def test_skips_falsy_ids(self, amazon_scraper, sample_amazon_job_data):
        out = amazon_scraper.deduplicate_jobs(
            [{"id": "", "title": "x"}, sample_amazon_job_data]
        )
        assert len(out) == 1

    def test_empty_list(self, amazon_scraper):
        assert amazon_scraper.deduplicate_jobs([]) == []
