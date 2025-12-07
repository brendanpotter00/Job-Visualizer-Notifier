"""
Pydantic data models for Google Jobs scraper
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class GoogleJob(BaseModel):
    """
    Job model aligned with the existing TypeScript Job interface
    """

    # Core fields (matching src/types/index.ts Job interface)
    id: str  # e.g., "114423471240291014"
    source: str = "google"  # New ATS provider
    company: str = "google"  # Always "google"
    title: str  # e.g., "Software Engineer III, Google Cloud"
    location: Optional[str] = None  # e.g., "Mountain View, CA, USA"
    createdAt: str  # ISO 8601 timestamp (using scraped_at as fallback)
    url: str  # Full job detail URL

    # Extended fields specific to Google
    experience_level: Optional[str] = None  # "Mid", "Advanced", "Early"
    minimum_qualifications: List[str] = Field(default_factory=list)
    preferred_qualifications: List[str] = Field(default_factory=list)
    about_the_job: Optional[str] = None
    responsibilities: List[str] = Field(default_factory=list)
    apply_url: Optional[str] = None
    salary_range: Optional[str] = None  # Extracted from about_the_job
    is_remote_eligible: bool = False

    # Metadata
    scraped_at: str  # When this job was scraped
    raw: dict = Field(default_factory=dict)  # Original scraped data for debugging


class ScraperOutput(BaseModel):
    """Output format for the JSON file"""

    scraped_at: str
    total_jobs: int  # Total jobs seen across all queries
    filtered_jobs: int  # After applying software/US filters and deduplication
    metadata: dict = Field(default_factory=dict)
    jobs: List[GoogleJob]


class CheckpointData(BaseModel):
    """Checkpoint data for resuming interrupted scrapes"""

    completed_queries: List[str] = Field(default_factory=list)
    jobs: List[GoogleJob] = Field(default_factory=list)
    total_jobs_seen: int = 0
    last_updated: str
