using JobsApi.Data.Entities;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace JobsApi.Controllers;

[ApiController]
[Route("api/[controller]")]
public class JobsController(JobsDbContext dbContext) : ControllerBase
{
    // GET /api/jobs - List all jobs with filtering
    [HttpGet]
    public async Task<ActionResult<IEnumerable<JobListing>>> GetJobs(
        [FromQuery] string? company = null,
        [FromQuery] string? status = "OPEN",
        [FromQuery] int limit = 1000,
        [FromQuery] int offset = 0)
    {
        var query = dbContext.JobListings.AsQueryable();

        if (!string.IsNullOrEmpty(company))
        {
            query = query.Where(j => j.Company == company);
        }

        // commented out for QA purposes -bp
        // if (!string.IsNullOrEmpty(status))
        // {
        //     query = query.Where(j => j.Status == status);
        // }

        var jobs = await query
            .OrderByDescending(j => j.LastSeenAt)
            .Skip(offset)
            .Take(limit)
            .ToListAsync();

        return Ok(jobs);
    }

    // GET /api/jobs/{id} - Get single job by ID
    [HttpGet("{id}")]
    public async Task<ActionResult<JobListing>> GetJob(string id)
    {
        var job = await dbContext.JobListings.FindAsync(id);

        if (job is null)
        {
            return NotFound();
        }

        return Ok(job);
    }
}
