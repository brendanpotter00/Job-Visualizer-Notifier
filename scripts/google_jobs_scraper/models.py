"""
Pydantic data models for Google Jobs scraper
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class JobListing(BaseModel):
    """
    Job model aligned with the JobListings database schema
    """

    # Primary fields
    id: str  # e.g., "114423471240291014"
    title: str  # e.g., "Software Engineer III, Google Cloud"
    company: str = "google"  # Always "google" for this scraper
    location: Optional[str] = None  # e.g., "Mountain View, CA, USA"
    url: str  # Full job detail URL
    source_id: str = "google_scraper"  # Workday, Lever, Greenhouse, Scraper, etc

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

    # Embedding placeholder (not used in JSON output)
    # embedding: Optional[List[float]] = None


# Alias for backwards compatibility
GoogleJob = JobListing


class ScraperOutput(BaseModel):
    """Output format for the JSON file"""

    scraped_at: str
    total_jobs: int  # Total jobs seen across all queries
    filtered_jobs: int  # After applying software/US filters and deduplication
    metadata: Dict[str, Any] = Field(default_factory=dict)
    jobs: List[JobListing]


class CheckpointData(BaseModel):
    """Checkpoint data for resuming interrupted scrapes"""

    completed_queries: List[str] = Field(default_factory=list)
    jobs: List[JobListing] = Field(default_factory=list)
    total_jobs_seen: int = 0
    last_updated: str
