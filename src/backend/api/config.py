"""Application configuration via environment variables."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/jobscraper"

    # Scraper settings
    scraper_interval_hours: int = Field(default=1, gt=0)
    scraper_companies: str = "apple,google,microsoft"
    scraper_detail_scrape: bool = True
    scraper_timeout_minutes: int = Field(default=90, gt=0)
    scraper_scripts_path: str = "../../scripts"
    scraper_python_path: str = "python3"

    # Database pool
    db_pool_min: int = Field(default=1, ge=1, le=20)
    db_pool_max: int = Field(default=15, ge=1, le=50)
    db_pool_timeout: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def validate_pool_bounds(self) -> "Settings":
        if self.db_pool_min > self.db_pool_max:
            raise ValueError(
                f"db_pool_min ({self.db_pool_min}) must not exceed db_pool_max ({self.db_pool_max})"
            )
        return self

    # Auth0 authentication
    auth0_domain: str | None = None
    auth0_audience: str | None = None

    # Google One Tap authentication
    google_client_id: str | None = None

    # Internal API key: shared secret between the Vercel serverless proxies
    # and this backend. When set, the require_internal_key middleware rejects
    # any request that doesn't present a matching X-Internal-Key header.
    # When unset (local dev), the middleware allows all requests through and
    # logs a startup warning.
    internal_api_key: str | None = None

    # Anthropic API key for location normalization (Tier 2 — Claude Haiku).
    # Read from the ANTHROPIC_API_KEY env var. When unset, the normalize
    # pipeline must degrade gracefully (later units): Tier 1 / schema / admin
    # endpoints operate normally and rows simply stay unnormalized. Plain
    # str|None to match internal_api_key (NOT SecretStr).
    anthropic_api_key: str | None = None

    # External enrichment (job-enricher pull integration). All default OFF. The
    # flag gates ONLY /pending: with it off, /pending hands out nothing, so no
    # rows are ever claimed/enriched and the cloud-Haiku location pipeline remains
    # the floor. (/results, /sample, /health are NOT flag-gated — they run
    # regardless; already-enriched facets persist even if the flag is later off.)
    # The laptop authenticates with the existing internal_api_key; JVN never
    # calls the laptop (pull model).
    enrichment_use_external: bool = False          # master flag; gates /pending
    enrichment_company_allowlist: str = ""         # csv; "" = all companies (gradual rollout)
    # Stale-claim reclaim window. MUST exceed a full enricher tick (one /pending →
    # classify → /results batch round-trip); otherwise an in-flight batch's rows
    # are reclaimed mid-flight and double-handed (wasting laptop tokens; only made
    # safe by the idempotent /results upsert).
    enrichment_claim_ttl_minutes: int = Field(default=15, gt=0)
    # If True, /results HOLDS judge-flagged rows as 'needs_human' (keyed on
    # judge.needs_human) instead of publishing them 'done'. Rows are held, NOT
    # dropped — the audit payload is still written either way.
    enrichment_require_judge_pass: bool = False

    # PostHog analytics
    posthog_project_token: str | None = None
    posthog_host: str = "https://us.i.posthog.com"

    # Public feedback endpoint rate limit (per client IP, sliding window).
    # Defaults are generous for a human but hostile to a script: 5 submissions
    # per 60s. Enforced in-process by services/rate_limit.py — see that module
    # for why an in-memory limiter is appropriate here.
    feedback_rate_limit_max: int = Field(default=5, gt=0)
    feedback_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # Server
    port: int = 8080
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    @property
    def companies_list(self) -> list[str]:
        return [c.strip() for c in self.scraper_companies.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enrichment_company_allowlist_list(self) -> list[str]:
        return [c.strip() for c in self.enrichment_company_allowlist.split(",") if c.strip()]

    model_config = {"env_file": (".env", ".env.local"), "extra": "ignore"}


settings = Settings()
