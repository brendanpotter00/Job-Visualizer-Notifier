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

    # Server
    port: int = 8080
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    @property
    def companies_list(self) -> list[str]:
        return [c.strip() for c in self.scraper_companies.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": (".env", ".env.local"), "extra": "ignore"}


settings = Settings()
