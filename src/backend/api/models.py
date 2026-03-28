"""Pydantic response models with camelCase serialization for frontend compatibility."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from typing import Optional


class JobListingResponse(BaseModel):
    """Matches frontend BackendJobListing interface (src/frontend/src/api/types.ts:190-208)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str
    company: str
    location: Optional[str] = None
    url: str
    source_id: str
    details: str  # JSON string, not parsed object
    created_at: str
    posted_on: Optional[str] = None
    closed_on: Optional[str] = None
    status: str
    has_matched: bool
    ai_metadata: str  # JSON string, not parsed object
    first_seen_at: str
    last_seen_at: str
    consecutive_misses: int
    details_scraped: bool


class ScrapeRunResponse(BaseModel):
    """Matches frontend ScrapeRun interface (src/frontend/src/pages/QAPage/QAPage.tsx:37-48)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: str
    company: str
    started_at: str
    completed_at: Optional[str] = None
    mode: str
    jobs_seen: int
    new_jobs: int
    closed_jobs: int
    details_fetched: int
    error_count: int


class CompanyCountResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    company: str
    count: int


class JobsStatsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_jobs: int
    open_jobs: int
    closed_jobs: int
    company_counts: list[CompanyCountResponse]


class ScraperResultResponse(BaseModel):
    """Response from trigger-scrape endpoint."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    exit_code: int
    output: str
    error: str
    company: str
    completed_at: str
