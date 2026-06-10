"""Pydantic response models with camelCase serialization for frontend compatibility."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
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


# --- Location-normalization admin models (Unit 8) ----------------------------

# Allowed values for a manual-override location spec's `kind`. Mirrors
# `_VALID_KINDS` in services.llm_client.CanonicalLocation so a manual override
# can produce exactly the same `locations` rows the LLM path produces.
LocationKind = Literal["city", "region", "country", "remote"]


class LocationSpec(BaseModel):
    """One canonical location in a manual alias-override request body.

    Mirrors services.llm_client.CanonicalLocation's structured fields (minus
    `confidence`, which is forced to 1.0 for manual overrides). The upsert into
    `locations` keys on (kind, city, region, country, remote_scope) against the
    NULLS-NOT-DISTINCT `uq_locations_canonical` constraint, exactly like the LLM
    write path.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    canonical_name: str = Field(min_length=1, max_length=200)
    kind: LocationKind
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    remote_scope: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _kind_remote_scope_invariant(self) -> "LocationSpec":
        """Enforce the kind <-> remote_scope cross-field rule.

        Mirrors services.llm_client.CanonicalLocation: a contradictory manual
        override (kind='remote' carrying city/region/country, or a non-remote
        kind carrying remote_scope) yields a 422 instead of silently writing a
        nonsensical canonical row.
        """
        if self.kind == "remote":
            if self.city is not None or self.region is not None or self.country is not None:
                raise ValueError(
                    "kind='remote' must have city/region/country all None; "
                    f"got city={self.city!r} region={self.region!r} country={self.country!r}"
                )
        elif self.remote_scope is not None:
            raise ValueError(
                f"remote_scope is only valid for kind='remote'; got kind={self.kind!r} "
                f"remote_scope={self.remote_scope!r}"
            )
        return self


class AdminAliasOverrideRequest(BaseModel):
    """Body for PUT /api/admin/locations/aliases/{raw_text}.

    `locations` is the ordered list of canonical locations this raw string maps
    to (position = list index). Manual overwrite semantics: this REPLACES any
    existing mapping for the normalized key and promotes the alias to
    source='manual' so it wins over a cached 'llm' guess (Decision #10).
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    # Bounded: a single raw string never maps to more than a handful of
    # locations (the multi-location prod max is 2). Cap defends against an
    # accidental huge body fanning out unbounded INSERTs.
    locations: list[LocationSpec] = Field(min_length=1, max_length=20)


class AdminLocationResponse(BaseModel):
    """A canonical location row as returned by the admin endpoints."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None
    position: int  # order within the alias mapping (alias_locations.position)


class AdminAliasResponse(BaseModel):
    """Result of a manual override OR one inspect row.

    `locations` is ordered by position. `confidence` is nullable (manual
    overrides set 1.0; llm aliases carry the averaged model confidence).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    raw_text: str
    source: str
    confidence: float | None = None
    locations: list[AdminLocationResponse]


class AdminAliasListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    aliases: list[AdminAliasResponse]


class AdminNormalizeJobResponse(BaseModel):
    """Result of POST /api/admin/jobs/{job_id}/normalize."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: str
    status: str  # "queued" | "reset_defer_failed" (reset committed; safety-net will pick it up)
    # False when ANTHROPIC_API_KEY is unset: the reset/defer still happened, but
    # a Tier-1 cache miss will dead-end until the key is configured (the job
    # stays NULL and auto-recovers once it is set). Surfaced so an explicit
    # admin action never silently no-ops.
    key_configured: bool


class AdminReNormalizeAllResponse(BaseModel):
    """Result of POST /api/admin/locations/re-normalize-all (break-glass)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    reset_count: int
    scan_deferred: bool
    # False when ANTHROPIC_API_KEY is unset: the reset is committed, but the
    # deferred scan skips while the key is absent — draining is PAUSED until the
    # key is set (then it auto-resumes on the next periodic tick). Surfaced so
    # the break-glass action never claims progress it can't make.
    key_configured: bool
    # Explicit, surfaced to the operator in the JSON body: this does NOT force
    # fresh LLM re-normalization — it re-applies the pipeline against the
    # current alias cache (incl. manual overrides). To force fresh LLM calls an
    # operator must clear aliases manually (deliberately not one-click).
    note: str
