# Backend API (JobsApi)

.NET 8 Web API that serves job data from PostgreSQL and runs automated scrapers.

## Commands

```bash
# From src/backend/JobsApi directory
dotnet run                    # Start API (Development mode, port 5000)
dotnet build                  # Build project
dotnet restore                # Restore NuGet packages

# From src/backend/JobsApi.Tests directory
dotnet test                   # Run all tests
dotnet test --verbosity normal  # Run with detailed output
```

## Prerequisites

- PostgreSQL running on localhost:5432 (use `docker compose up -d postgres` from project root)
- Database: `jobscraper` with tables `job_listings_local` and `scrape_runs_local`

## Key Configuration

**Environment-based table naming:**
- `Scraper:Environment` in appsettings controls table suffixes
- Development: `job_listings_local`, `scrape_runs_local`
- Production: `job_listings_prod`, `scrape_runs_prod`

**Scraper settings (appsettings.json):**
- `Scraper:IntervalHours` - Hours between automatic scrape cycles (default: 1)
- `Scraper:Companies` - Array of companies to scrape (e.g., ["google", "apple"])
- `Scraper:DetailScrape` - Whether to fetch job details (default: true)
- `Scraper:TimeoutMinutes` - Max time per scrape before killing (default: 60)
- `Scraper:ScriptsPath` - Path to Python scripts directory
- `Scraper:PythonPath` - Path to Python interpreter

## API Endpoints

**Jobs Controller (`/api/jobs`):**
- `GET /api/jobs` - List jobs (params: company, status, limit, offset)
- `GET /api/jobs/{id}` - Get single job by ID

**QA Controller (`/api/jobs-qa`):**
- `GET /api/jobs-qa/stats` - Job statistics (params: company; returns total, open, closed, by company)
- `GET /api/jobs-qa/scrape-runs` - Scrape run history (params: company, limit)
- `POST /api/jobs-qa/trigger-scrape` - Manually trigger scraper (params: company; default: google)

**Health:**
- `GET /health` - Health check

## Key Files

**Controllers:**
- `Controllers/JobsController.cs` - Main jobs API
- `Controllers/JobsQAController.cs` - QA/debugging endpoints

**Data/Entities:**
- `Data/Entities/JobsDbContext.cs` - EF Core context with dynamic table naming
- `Data/Entities/JobListing.cs` - Job entity model
- `Data/Entities/ScrapeRun.cs` - Scrape run entity model
- `Data/Entities/JobsStats.cs` - Stats response DTO (includes CompanyCount)

**Services:**
- `Services/ScraperProcessRunner.cs` - Python scraper integration (includes ScraperResult, ConnectionStringHelper)
- `Services/AutoScraperService.cs` - Background service for scheduled scraping

**Config:**
- `Program.cs` - App configuration and middleware
- `appsettings.json` - Default configuration
- `appsettings.Development.json` - Development overrides

## Tests

The `JobsApi.Tests` project contains xUnit tests with Moq for mocking:
- `Controllers/JobsQAControllerTests.cs` - QA endpoint tests
- `Services/ScraperProcessRunnerTests.cs` - Scraper service tests
