"""
Pydantic data models for job scrapers

These models are aligned with the database schema and support incremental scraping.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal


class JobListing(BaseModel):
    """
    Job model aligned with the database schema
    Supports incremental tracking of job lifecycle
    """

    # Primary fields
    id: str  # e.g., "114423471240291014"
    title: str  # e.g., "Software Engineer III, Google Cloud"
    company: str  # "google", "apple", etc.
    location: Optional[str] = None  # e.g., "Mountain View, CA, USA"
    url: str  # Full job detail URL
    source_id: str  # "google_scraper", "workday_scraper", etc.

    # Details JSONB - qualifications, description, etc.
    details: Dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    posted_on: Optional[str] = None  # When job was posted (if available)
    created_at: str  # First time we saw it (ISO 8601)
    closed_on: Optional[str] = None  # When job was closed (null if still open)

    # Status
    status: Literal["OPEN", "CLOSED"] = "OPEN"

    # AI matching fields
    has_matched: bool = False  # Has gone through AI notification service
    ai_metadata: Dict[str, Any] = Field(default_factory=dict)  # AI matched tags

    # Incremental tracking fields
    first_seen_at: str  # When we first discovered this job
    last_seen_at: str  # Last time we saw this job in search results
    consecutive_misses: int = 0  # Number of consecutive scrapes where job was missing
    details_scraped: bool = False  # Whether we've scraped the detail page


class ScrapeRun(BaseModel):
    """
    Metadata about a scrape run
    Used for tracking scrape history and performance
    """

    run_id: str  # Unique identifier for this scrape run
    company: str  # "google", "apple", etc.
    started_at: str  # ISO 8601 timestamp
    completed_at: Optional[str] = None  # ISO 8601 timestamp (null if failed/ongoing)
    mode: Literal["incremental", "full"]
    jobs_seen: int = 0  # Total jobs found in search results
    new_jobs: int = 0  # New jobs discovered (not in DB before)
    closed_jobs: int = 0  # Jobs marked as closed this run
    details_fetched: int = 0  # Number of detail pages scraped
    error_count: int = 0  # Number of errors encountered
    # True when the safety guard tripped and the destructive update/close
    # phases were skipped. Before this field existed a truncated run was
    # written as error_count=0 and was indistinguishable from a perfect run.
    # Defaults to False here (the writer always knows); the DB column is
    # nullable so pre-existing rows stay honestly NULL = "unknown".
    skipped_update: bool = False
    # WHICH rule tripped: None | "empty_scrape" | "partial_scrape" |
    # "unverified_harvest".
    # ``skipped_update`` alone cannot answer that — both safety-guard rules set
    # it — and the bounded auto-release must count ONLY partial_scrape, or a total
    # outage (rule (a), explicitly never released) would supply the repetition
    # evidence that releases the next truncated run.
    #
    # The E7 members are a DIFFERENT axis: each names why a custom-company
    # harvest's destructive close phase was skipped even though the upsert ran
    # ("unverified_harvest" = not proven complete; "approximate_no_close" =
    # tolerance>0; "fleet_breaker" = >20% of the night's custom runs failed;
    # "first_verified_run"/"script_changed" = a first/post-change run closes
    # nothing; "streak_too_short" = a self_consistent company below its 3-run
    # streak; "id_churn_suspected" = a self_consistent board whose id set churned
    # >50% in one run with no total to corroborate the drop). None of them count
    # toward the partial_scrape auto-release — ``count_consecutive_partial_skips``
    # filters on 'partial_scrape' specifically. This Literal MUST stay in lockstep
    # with ``incremental.GuardReason``, the source these strings are assigned from.
    guard_reason: Optional[
        Literal[
            "empty_scrape",
            "partial_scrape",
            "unverified_harvest",
            "approximate_no_close",
            "fleet_breaker",
            "first_verified_run",
            "script_changed",
            "streak_too_short",
            "id_churn_suspected",
        ]
    ] = None
    # --- Custom company sources (E7) -----------------------------------------
    # Per-company ``custom:<id>`` namespace for a custom company's runs (None for
    # the six public ATS crons). ``success`` is the run's boolean outcome as the
    # custom leaf task sees it (None for the six ATS tasks, which encode outcome
    # via error_count / skipped_update / guard_reason instead).
    source_id: Optional[str] = None
    success: Optional[bool] = None
