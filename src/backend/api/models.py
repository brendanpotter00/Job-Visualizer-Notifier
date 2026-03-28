"""Pydantic response models with camelCase serialization for frontend compatibility."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class JobListingResponse(BaseModel):
    """Matches the frontend BackendJobListing TypeScript interface."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str
    company: str
    location: str | None = None
    url: str
    source_id: str
    details: str  # JSON string, not parsed object
    created_at: str
    posted_on: str | None = None
    closed_on: str | None = None
    status: Literal["OPEN", "CLOSED"]
    has_matched: bool
    ai_metadata: str  # JSON string, not parsed object
    first_seen_at: str
    last_seen_at: str
    consecutive_misses: int = Field(ge=0)
    details_scraped: bool


class ScrapeRunResponse(BaseModel):
    """Matches the frontend ScrapeRunResponse TypeScript interface."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    run_id: str
    company: str
    started_at: str
    completed_at: str | None = None
    mode: Literal["incremental", "full"]
    jobs_seen: int = Field(ge=0)
    new_jobs: int = Field(ge=0)
    closed_jobs: int = Field(ge=0)
    details_fetched: int = Field(ge=0)
    error_count: int = Field(ge=0)


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
