"""``details_scraped`` must mean something.

It is supposed to say "we have this job's detail content, not just its list-view stub".
Every ATS client hard-coded it to ``True``, so against prod it was true for 100% of rows
on every Workday company (capitalone 4,587, gm 3,415, blueorigin 2,980, disney 2,357,
nvidia 1,722, …) and on Netflix/Eightfold (1,172) — every one of which has no
description at all. A flag that is true for every row carries no information, and this
one was worse than uninformative: it asserted the opposite of the truth on ~19,000 rows.

These run offline against the transform functions directly, no HTTP.
"""

from __future__ import annotations

import re

from api.services import (
    ashby_client,
    eightfold_client,
    gem_client,
    greenhouse_client,
    lever_client,
    workday_client,
)
from api.services.enrichment_monitor import DESCRIPTION_SQL
from api.services.job_details import DESCRIPTION_KEYS, has_description


class TestHasDescription:
    def test_a_real_description_counts(self) -> None:
        assert has_description({"description_html": "<p>Build things.</p>"}) is True

    def test_every_known_storage_key_counts(self) -> None:
        """One key per ATS. A key missing from the set is a whole ATS silently
        reporting ``details_scraped=False`` on rows that do have descriptions."""
        for key in DESCRIPTION_KEYS:
            assert has_description({key: "text"}) is True, key

    def test_a_json_null_description_does_not_count(self) -> None:
        """Workday's exact shape. It builds the key so the JSONB matches the other
        ATSs, then leaves it None — which is precisely the 11,901-row lie."""
        assert has_description({"description_html": None, "department": "Eng"}) is False

    def test_an_empty_string_description_does_not_count(self) -> None:
        """``DESCRIPTION_SQL`` COALESCEs an empty ``about_the_job`` away, so treating
        it as present here would put the write side and the read side in disagreement
        about the same row."""
        assert has_description({"about_the_job": ""}) is False

    def test_no_description_key_at_all_does_not_count(self) -> None:
        """Eightfold's list payload carries department/team/locations and no
        description key whatsoever."""
        assert has_description({"department": "Eng", "team": "Core"}) is False

    def test_empty_and_missing_details_do_not_count(self) -> None:
        assert has_description({}) is False
        assert has_description(None) is False

    def test_the_key_set_matches_the_read_side_predicate(self) -> None:
        """Drift guard. ``DESCRIPTION_SQL`` decides which rows the enrichment pipeline
        may claim; ``DESCRIPTION_KEYS`` decides which rows we claim to have scraped.
        If they disagree, one of the two is lying about the same row."""
        sql_keys = tuple(re.findall(r"details->>'([a-z_]+)'", DESCRIPTION_SQL))
        assert sql_keys == DESCRIPTION_KEYS


class TestClientsSetItFromTheData:
    """The six ATS clients, each with and without a description."""

    def test_ashby(self) -> None:
        raw = {"id": "1", "title": "SWE", "jobUrl": "https://x/1"}
        with_desc = ashby_client.transform_to_job_listings(
            "c", [{**raw, "descriptionHtml": "<p>hi</p>"}]
        )
        without = ashby_client.transform_to_job_listings("c", [raw])
        assert with_desc[0].details_scraped is True
        assert without[0].details_scraped is False

    def test_lever(self) -> None:
        raw = {"id": "1", "text": "SWE", "hostedUrl": "https://x/1", "categories": {}}
        with_desc = lever_client.transform_to_job_listings(
            "c", [{**raw, "description": "<p>hi</p>"}]
        )
        without = lever_client.transform_to_job_listings("c", [raw])
        assert with_desc[0].details_scraped is True
        assert without[0].details_scraped is False

    def test_greenhouse(self) -> None:
        raw = {"id": 1, "title": "SWE", "absolute_url": "https://x/1"}
        with_desc = greenhouse_client.transform_to_job_listings(
            "c", [{**raw, "content": "<p>hi</p>"}]
        )
        without = greenhouse_client.transform_to_job_listings("c", [raw])
        assert with_desc[0].details_scraped is True
        assert without[0].details_scraped is False

    def test_gem(self) -> None:
        raw = {"id": 1, "title": "SWE", "absolute_url": "https://x/1"}
        with_desc = gem_client.transform_to_job_listings(
            "c", [{**raw, "content": "<p>hi</p>"}]
        )
        without = gem_client.transform_to_job_listings("c", [raw])
        assert with_desc[0].details_scraped is True
        assert without[0].details_scraped is False

    def test_eightfold_never_claims_a_description(self) -> None:
        """Netflix, 1,172 rows in prod. The list payload has no description key at
        all, so this one is structurally always False — and saying so is the fix."""
        jobs = eightfold_client.transform_to_job_listings(
            "netflix",
            [{"id": "1", "name": "SWE", "canonicalPositionUrl": "https://x/1"}],
        )
        assert jobs and jobs[0].details_scraped is False

    def test_workday_never_claims_a_description(self) -> None:
        """``description_html`` is hard-coded None in ``workday_client``, which is why
        all 11,901 Workday rows plus custom Cisco (1,246) and Intel (613) were flagged
        while carrying nothing."""
        jobs = workday_client.transform_to_job_listings(
            "nvidia",
            [{
                "title": "SWE",
                "externalPath": "/job/US-CA/SWE_JR0001",
                "locationsText": "Santa Clara, CA",
                "bulletFields": ["JR0001"],
            }],
            {
                "base_url": "https://nvidia.wd5.myworkdayjobs.com",
                "tenant_slug": "nvidia",
                "career_site_slug": "NVIDIAExternalCareerSite",
            },
        )
        assert jobs and jobs[0].details_scraped is False
