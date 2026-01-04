using JobsApi.Data.Entities;
using JobsApi.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace JobsApi.Controllers;

[ApiController]
[Route("api/jobs-qa")]
public class JobsQAController(
    JobsDbContext dbContext,
    ScraperProcessRunner processRunner,
    ILogger<JobsQAController> logger) : ControllerBase
{
    // GET /api/jobs-qa/stats - Get job statistics
    [HttpGet("stats")]
    public async Task<ActionResult<JobsStats>> GetStats([FromQuery] string? company = null)
    {
        var query = dbContext.JobListings.AsQueryable();

        if (!string.IsNullOrEmpty(company))
        {
            query = query.Where(j => j.Company == company);
        }

        var stats = new JobsStats
        {
            TotalJobs = await query.CountAsync(),
            OpenJobs = await query.CountAsync(j => j.Status == "OPEN"),
            ClosedJobs = await query.CountAsync(j => j.Status == "CLOSED"),
            CompanyCounts = await query
                .GroupBy(j => j.Company)
                .Select(g => new CompanyCount { Company = g.Key, Count = g.Count() })
                .ToListAsync()
        };

        return Ok(stats);
    }

    // GET /api/jobs-qa/scrape-runs - Get scrape run history
    [HttpGet("scrape-runs")]
    public async Task<ActionResult<IEnumerable<ScrapeRun>>> GetScrapeRuns(
        [FromQuery] string? company = null,
        [FromQuery] int limit = 20)
    {
        var query = dbContext.ScrapeRuns.AsQueryable();

        if (!string.IsNullOrEmpty(company))
        {
            query = query.Where(r => r.Company == company);
        }

        var runs = await query
            .OrderByDescending(r => r.StartedAt)
            .Take(limit)
            .ToListAsync();

        return Ok(runs);
    }

    // POST /api/jobs-qa/trigger-scrape - Manually trigger a scrape
    [HttpPost("trigger-scrape")]
    public async Task<ActionResult<ScraperResult>> TriggerScrape(
        [FromQuery] string company = "google",
        CancellationToken cancellationToken = default)
    {
        logger.LogInformation("Manual scrape triggered for {Company}", company);

        var result = await processRunner.RunScraperAsync(company, cancellationToken);

        if (result.ExitCode != 0)
        {
            logger.LogError("Scrape failed for {Company}: {Error}", company, result.Error);
            return StatusCode(500, result);
        }

        return Ok(result);
    }
}
