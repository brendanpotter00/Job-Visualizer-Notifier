# Backend API (JobsApi)

.NET 8 Web API that serves job data from PostgreSQL and runs automated scrapers.

## Commands

```bash
# From src/backend/JobsApi directory
dotnet run                    # Start API (Development mode, port 5000)
dotnet build                  # Build project
dotnet restore                # Restore NuGet packages
```

## Prerequisites

- PostgreSQL running on localhost:5432 (use `docker compose up -d postgres` from project root)
- Database: `jobscraper` with tables `job_listings_local` and `scrape_runs_local`

## Key Configuration

**Environment-based table naming:**
- `Scraper:Environment` in appsettings controls table suffixes
- Development: `job_listings_local`, `scrape_runs_local`
- Production: `job_listings_prod`, `scrape_runs_prod`

## API Endpoints

**Jobs Controller (`/api/jobs`):**
- `GET /api/jobs` - List jobs (params: company, status, limit, offset)
- `GET /api/jobs/{id}` - Get single job by ID

**QA Controller (`/api/jobs-qa`):**
- `GET /api/jobs-qa/stats` - Job statistics (total, by company, by status)
- `GET /api/jobs-qa/scrape-runs` - Scrape run history
- `POST /api/jobs-qa/trigger-scrape` - Manually trigger Google scraper

**Health:**
- `GET /health` - Health check

## Key Files

- `Controllers/JobsController.cs` - Main jobs API
- `Controllers/JobsQAController.cs` - QA/debugging endpoints
- `Data/Entities/JobsDbContext.cs` - EF Core context with dynamic table naming
- `Data/Entities/JobListing.cs` - Job entity model
- `Data/Entities/ScrapeRun.cs` - Scrape run entity model
- `Services/ScraperProcessRunner.cs` - Python scraper integration
- `Services/AutoScraperService.cs` - Background service for scheduled scraping
- `Program.cs` - App configuration and middleware
