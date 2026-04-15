"""Pydantic response models with camelCase serialization for frontend compatibility."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Shared validation pattern for company name query parameters
COMPANY_PATTERN = r"^[a-zA-Z0-9_-]+$"


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
    created_at: datetime
    posted_on: datetime | None = None
    closed_on: datetime | None = None
    status: Literal["OPEN", "CLOSED"]
    has_matched: bool
    ai_metadata: str  # JSON string, not parsed object
    first_seen_at: datetime
    last_seen_at: datetime
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


class UserResponse(BaseModel):
    """User profile at the API boundary.

    The ``provider_subject`` field tracks the *most recent* identity provider's
    subject (Auth0 ``sub`` or Google-prefixed One Tap ``sub``). It maps to the
    DB column ``auth0_id`` for historical reasons — the column predates Google
    One Tap support — but the model name reflects that the value is no longer
    Auth0-specific. See ``docs/implementations/auth0/REVIEW_AUDIT.md``.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    provider_subject: str
    email: str
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture_url: str | None = None
    created_at: str
    updated_at: str


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)
