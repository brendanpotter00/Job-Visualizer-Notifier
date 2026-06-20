"""Shared spec table + data-integrity assertions for the live scraper E2E suite.

These tests exist because a *silently-broken* Playwright scraper is what skews
metrics: the open/closed lifecycle in ``shared/incremental.py`` marks a job
``CLOSED`` after ``MISSED_RUN_THRESHOLD = 2`` consecutive scrapes where it is
absent. If a scraper returns 0 (or far too few) jobs — because Google/Apple/
Microsoft changed their DOM/API, or the browser environment broke — every job
it "missed" gets falsely closed. That exact failure mode mass-closed 3,582 Apple
jobs (failure began 2026-03-28; see
``docs/incidents/2026-03-29-mass-job-closure.md``).

The unit/integration suite already covers the lifecycle *logic* with mocks. This
module covers the part mocks cannot: that the real scrapers still return a
healthy volume of well-formed jobs against the live sites.

``assert_job_integrity`` reuses each scraper's own ``transform_to_job_model`` so
every scraped card must construct a valid ``JobListing`` Pydantic model — the
canonical data contract.

Coverage note: ``posted_on`` is only validated where the list card actually
carries it. In list-only mode that is Microsoft alone — its transform reads
``posted_on``/``posted_date`` — while Google and Apple list cards leave
``posted_on=None`` (Apple's list card emits ``posted_date`` but its transform
reads ``posted_on``), so the parse branch is exercised for Microsoft and skipped
for the other two.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Pattern

from dateutil import parser as date_parser

from shared.base_scraper import BaseScraper
from shared.constants import SourceId

from google_jobs_scraper.scraper import GoogleJobsScraper
from apple_jobs_scraper.scraper import AppleJobsScraper
from microsoft_jobs_scraper.scraper import MicrosoftJobsScraper


@dataclass(frozen=True)
class ScraperSpec:
    """Per-scraper E2E configuration and integrity expectations."""

    name: str
    factory: Callable[[], BaseScraper]
    source_id: str
    # Stop the live scrape once this many jobs are collected (bounds runtime).
    max_jobs: int
    # Health floor: the canary for the 0-job / too-few-jobs mass-closure
    # scenario. Kept conservatively below max_jobs so a healthy scrape always
    # clears it while a broken scrape (0 or a handful) trips it.
    min_jobs: int
    # Well-formed external job id (catches "unknown"/garbage ids).
    id_pattern: Pattern[str]
    # Every job url must start with this (catches relative/wrong-host urls).
    url_prefix: str
    # Fraction of jobs that must carry a non-empty location. Lenient so a
    # heuristic miss doesn't fail, but a wholesale location break (0%) does.
    min_location_coverage: float = 0.25


SCRAPER_SPECS: List[ScraperSpec] = [
    ScraperSpec(
        name="google",
        factory=lambda: GoogleJobsScraper(headless=True, detail_scrape=False),
        source_id=SourceId.GOOGLE,
        max_jobs=30,
        min_jobs=10,
        id_pattern=re.compile(r"^\d+$"),
        url_prefix="https://www.google.com",
    ),
    ScraperSpec(
        name="apple",
        factory=lambda: AppleJobsScraper(headless=True, detail_scrape=False),
        source_id=SourceId.APPLE,
        max_jobs=30,
        min_jobs=10,
        # Apple ids carry a location suffix, e.g. "200640732-0836".
        id_pattern=re.compile(r"^\d[\w-]*$"),
        url_prefix="https://jobs.apple.com",
    ),
    ScraperSpec(
        name="microsoft",
        factory=lambda: MicrosoftJobsScraper(headless=True, detail_scrape=False),
        source_id=SourceId.MICROSOFT,
        max_jobs=30,
        min_jobs=10,
        id_pattern=re.compile(r"^\d+$"),
        url_prefix="https://apply.careers.microsoft.com",
    ),
]


def assert_job_integrity(
    raw_jobs: List[Dict],
    spec: ScraperSpec,
    scraper: BaseScraper,
) -> None:
    """Assert every data-integrity invariant for a live scrape.

    Args:
        raw_jobs: Job-card dicts as returned by ``scrape_all_queries``.
        spec: The scraper's spec (floors, patterns, host).
        scraper: The scraper instance (for ``transform_to_job_model`` — pure,
            no browser needed).
    """
    # --- Health floor: the load-bearing assertion ---------------------------
    assert len(raw_jobs) >= spec.min_jobs, (
        f"[{spec.name}] scraper returned only {len(raw_jobs)} jobs "
        f"(floor {spec.min_jobs}). A scrape this thin would falsely close jobs "
        f"via the consecutive-misses lifecycle — the scraper is likely broken "
        f"(DOM/API change or browser failure)."
    )

    # --- Valid model: every card must build a valid JobListing --------------
    # transform_to_job_model runs Pydantic validation; a bad shape raises here.
    jobs = [scraper.transform_to_job_model(card) for card in raw_jobs]

    ids: List[str] = []
    located = 0
    for job in jobs:
        ctx = f"[{spec.name}] job id={job.id!r} title={job.title!r}"

        # Required fields non-empty
        assert job.id and job.id != "unknown", f"{ctx}: missing/unknown id"
        assert job.title and job.title.strip(), f"{ctx}: empty title"
        assert job.url and job.url.strip(), f"{ctx}: empty url"

        # Well-formed id
        assert spec.id_pattern.match(job.id), (
            f"{ctx}: id does not match expected pattern {spec.id_pattern.pattern}"
        )

        # Valid url pointing at the expected host
        assert job.url.startswith(spec.url_prefix), (
            f"{ctx}: url {job.url!r} does not start with {spec.url_prefix!r}"
        )

        # source_id stamped correctly
        assert job.source_id == spec.source_id, (
            f"{ctx}: source_id {job.source_id!r} != {spec.source_id!r}"
        )

        # Fresh-scrape lifecycle state must be OPEN / not closed
        assert job.status == "OPEN", f"{ctx}: fresh job not OPEN (got {job.status})"
        assert job.closed_on is None, f"{ctx}: fresh job has closed_on set"

        # posted_on must be parseable when present. In list-only mode only
        # Microsoft populates posted_on (see module docstring), so this branch
        # is exercised for Microsoft and skipped for Google/Apple (posted_on is
        # None for them).
        if job.posted_on is not None:
            try:
                date_parser.parse(job.posted_on)
            except (ValueError, OverflowError, TypeError) as exc:
                raise AssertionError(
                    f"{ctx}: posted_on {job.posted_on!r} is not parseable: {exc}"
                )

        ids.append(job.id)
        if job.location and job.location.strip():
            located += 1

    # --- Unique ids: dedup / primary-key-collision guard --------------------
    duplicates = [i for i in set(ids) if ids.count(i) > 1]
    assert not duplicates, (
        f"[{spec.name}] duplicate job ids in a single scrape: {duplicates[:5]} "
        f"(a (source_id, id) collision would clobber rows on upsert)"
    )

    # --- Location coverage: catch a wholesale location-extraction break -----
    coverage = located / len(jobs)
    assert coverage >= spec.min_location_coverage, (
        f"[{spec.name}] only {coverage:.0%} of jobs have a location "
        f"(floor {spec.min_location_coverage:.0%}) — location extraction likely broke"
    )
