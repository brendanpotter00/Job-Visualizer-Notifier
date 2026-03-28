"""Application configuration via environment variables."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

ALLOWED_ENVIRONMENTS = {"local", "qa", "prod"}


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/jobscraper"

    # Scraper settings
    scraper_environment: str = "local"

    @field_validator("scraper_environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in ALLOWED_ENVIRONMENTS:
            raise ValueError(
                f"Invalid scraper_environment: {v!r}. Must be one of {sorted(ALLOWED_ENVIRONMENTS)}"
            )
        return v

    scraper_interval_hours: int = Field(default=1, gt=0)
    scraper_companies: str = "apple,google,microsoft"
    scraper_detail_scrape: bool = True
    scraper_timeout_minutes: int = Field(default=90, gt=0)
    scraper_scripts_path: str = "../../scripts"
    scraper_python_path: str = "python3"

    # Server
    port: int = 8080
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    @property
    def companies_list(self) -> list[str]:
        return [c.strip() for c in self.scraper_companies.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
