"""Pydantic response models with camelCase serialization for frontend compatibility."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

# Closed set of signup provider tokens derived from
# ``_signup_provider_from_auth0_id`` in ``services.admin_service``. Keeping
# this as a module-level alias means a new provider added to that mapping
# is a TS *and* Python compile error at every consumer — no silent fallback
# to a raw string key in the admin dashboard.
SignupProvider = Literal["google", "email", "other"]

# Shared validation pattern for company name query parameters.
# Backend-scraped companies only (google, apple, microsoft) — no dots needed.
COMPANY_PATTERN = r"^[a-zA-Z0-9_-]+$"

# Pattern for frontend company IDs stored in user preferences. Allows interior
# dots so IDs like ``happyrobot.ai`` round-trip, but still rejects leading/
# trailing dots and ``..`` — no path-traversal shapes reach the DB layer.
ENABLED_COMPANY_ID_PATTERN = r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$"

CompanyId = Annotated[
    str,
    StringConstraints(pattern=ENABLED_COMPANY_ID_PATTERN, min_length=1, max_length=64),
]


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
    # Required (no default) — a future endpoint that forgets to compute the
    # admin flag will fail Pydantic validation rather than silently demoting
    # the user to non-admin in the response.
    is_admin: bool


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)


class EnabledCompaniesResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    company_ids: list[str]
    # When true, companies added after the user's last save auto-enroll into
    # their feed on read. See user_preferences_service.list_enabled_companies.
    auto_enroll_new_companies: bool = True


class EnabledCompaniesUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    # Cap is well above the company catalogue size: auto-enroll materializes
    # full-catalogue lists for "Select All" / see-all users, so a save payload
    # can legitimately contain every company id. 200 was too tight once the
    # catalogue passed ~119 and keeps growing.
    company_ids: list[CompanyId] = Field(max_length=1000)
    auto_enroll_new_companies: bool = True


class FeatureResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    title: str
    description: str
    created_at: datetime
    upvote_count: int = Field(ge=0)
    has_upvoted: bool


class FeatureListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    features: list[FeatureResponse]


class FeatureUpvoteStateResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    feature_id: str
    upvote_count: int = Field(ge=0)
    has_upvoted: bool


class AdminUserRow(BaseModel):
    """One row in the admin Users page roster."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    email: str
    display_name: str | None = None
    signup_provider: SignupProvider
    created_at: str
    is_admin: bool


class AdminUsersListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    users: list[AdminUserRow]


class AdminUsersStatsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_users: int = Field(ge=0)
    first_signup_at: str | None = None
    latest_signup_at: str | None = None
    # Aggregate may omit zero-count providers, so this dict is partial.
    # Typed as ``SignupProvider`` (not ``str``) so adding a new provider
    # to ``_signup_provider_from_auth0_id`` is a compile-time error here
    # rather than rendering raw keys to admins.
    by_provider: dict[SignupProvider, int]
