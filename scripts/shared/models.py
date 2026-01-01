"""
Pydantic data models for job scrapers

These models are aligned with the database schema and support incremental scraping.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


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
    status: str = "OPEN"  # OPEN / CLOSED

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
    mode: str  # "incremental" or "full"
    jobs_seen: int = 0  # Total jobs found in search results
    new_jobs: int = 0  # New jobs discovered (not in DB before)
    closed_jobs: int = 0  # Jobs marked as closed this run
    details_fetched: int = 0  # Number of detail pages scraped
    error_count: int = 0  # Number of errors encountered
