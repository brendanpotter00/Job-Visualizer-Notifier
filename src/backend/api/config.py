"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/jobscraper"

    # Scraper settings
    scraper_environment: str = "local"
    scraper_interval_hours: int = 1
    scraper_companies: str = "apple,google,microsoft"
    scraper_detail_scrape: bool = True
    scraper_timeout_minutes: int = 90
    scraper_scripts_path: str = "../../scripts"
    scraper_python_path: str = "python3"

    # Server
    port: int = 8080

    @property
    def companies_list(self) -> list[str]:
        return [c.strip() for c in self.scraper_companies.split(",") if c.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
