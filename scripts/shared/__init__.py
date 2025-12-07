"""
Shared modules for job scrapers

This package contains shared functionality used across multiple company scrapers:
- models: Pydantic models aligned with database schema
- database: Database abstraction layer (SQLite/PostgreSQL)
- incremental: 5-phase incremental scraping algorithm
- base_scraper: Abstract base class for company-specific scrapers
"""

__version__ = "1.0.0"
