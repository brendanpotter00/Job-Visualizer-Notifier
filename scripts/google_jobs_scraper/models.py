"""
Pydantic data models for Google Jobs scraper

Re-exports shared models and provides Google-specific aliases.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

# Import from shared models to avoid duplication
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.models import JobListing

# Alias for Google-specific code
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
