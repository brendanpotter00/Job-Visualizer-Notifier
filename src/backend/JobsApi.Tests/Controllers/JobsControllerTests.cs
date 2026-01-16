using JobsApi.Controllers;
using JobsApi.Data.Entities;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace JobsApi.Tests.Controllers;

public class JobsControllerTests : IDisposable
{
    private readonly JobsDbContext _dbContext;

    public JobsControllerTests()
    {
        // Create in-memory database for testing
        var options = new DbContextOptionsBuilder<JobsDbContext>()
            .UseInMemoryDatabase(databaseName: Guid.NewGuid().ToString())
            .Options;
        _dbContext = new JobsDbContext(options);

        // Seed test data
        SeedTestData();
    }

    private void SeedTestData()
    {
        _dbContext.JobListings.AddRange(
            new JobListing
            {
                Id = "google-123",
                Title = "Software Engineer",
                Company = "google",
                Location = "Mountain View, CA",
                Url = "https://careers.google.com/jobs/123",
                SourceId = "google_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-10T10:00:00Z",
                FirstSeenAt = "2025-01-10T10:00:00Z",
                LastSeenAt = "2025-01-15T10:00:00Z"
            },
            new JobListing
            {
                Id = "google-456",
                Title = "Data Scientist",
                Company = "google",
                Location = "New York, NY",
                Url = "https://careers.google.com/jobs/456",
                SourceId = "google_scraper",
                Status = "CLOSED",
                CreatedAt = "2025-01-05T10:00:00Z",
                FirstSeenAt = "2025-01-05T10:00:00Z",
                LastSeenAt = "2025-01-12T10:00:00Z"
            },
            new JobListing
            {
                Id = "apple-789",
                Title = "Machine Learning Engineer",
                Company = "apple",
                Location = "Cupertino, CA",
                Url = "https://jobs.apple.com/details/789",
                SourceId = "apple_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-08T10:00:00Z",
                FirstSeenAt = "2025-01-08T10:00:00Z",
                LastSeenAt = "2025-01-16T10:00:00Z"
            },
            new JobListing
            {
                Id = "apple-101",
                Title = "iOS Developer",
                Company = "apple",
                Location = "Austin, TX",
                Url = "https://jobs.apple.com/details/101",
                SourceId = "apple_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-12T10:00:00Z",
                FirstSeenAt = "2025-01-12T10:00:00Z",
                LastSeenAt = "2025-01-14T10:00:00Z"
            }
        );
        _dbContext.SaveChanges();
    }

    [Fact]
    public async Task GetJobs_ReturnsAllJobs_WhenNoFilters()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJobs();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Equal(4, jobs.Count());
    }

    [Fact]
    public async Task GetJobs_ReturnsJobsForCompany_Google()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJobs(company: "google");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Equal(2, jobs.Count());
        Assert.All(jobs, job => Assert.Equal("google", job.Company));
    }

    [Fact]
    public async Task GetJobs_ReturnsAppleJobs()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJobs(company: "apple");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Equal(2, jobs.Count());
        Assert.All(jobs, job => Assert.Equal("apple", job.Company));
    }

    [Fact]
    public async Task GetJobs_AppliesPagination_Limit()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJobs(limit: 2);

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Equal(2, jobs.Count());
    }

    [Fact]
    public async Task GetJobs_AppliesPagination_Offset()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act - Get jobs starting from offset 2
        var result = await controller.GetJobs(offset: 2);

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Equal(2, jobs.Count());
    }

    [Fact]
    public async Task GetJobs_AppliesPagination_LimitAndOffset()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act - Get 1 job starting from offset 1
        var result = await controller.GetJobs(limit: 1, offset: 1);

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Single(jobs);
    }

    [Fact]
    public async Task GetJobs_ReturnsEmpty_WhenCompanyNotFound()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJobs(company: "nonexistent");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Empty(jobs);
    }

    [Fact]
    public async Task GetJobs_OrdersByLastSeenAtDescending()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJobs();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value).ToList();

        // Jobs should be ordered by LastSeenAt descending
        for (int i = 0; i < jobs.Count - 1; i++)
        {
            Assert.True(
                string.Compare(jobs[i].LastSeenAt, jobs[i + 1].LastSeenAt) >= 0,
                $"Job {jobs[i].Id} with LastSeenAt {jobs[i].LastSeenAt} should come before {jobs[i + 1].Id} with LastSeenAt {jobs[i + 1].LastSeenAt}"
            );
        }
    }

    [Fact]
    public async Task GetJob_ReturnsJobById()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJob("google-123");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var job = Assert.IsType<JobListing>(okResult.Value);
        Assert.Equal("google-123", job.Id);
        Assert.Equal("Software Engineer", job.Title);
        Assert.Equal("google", job.Company);
    }

    [Fact]
    public async Task GetJob_ReturnsAppleJobById()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJob("apple-789");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var job = Assert.IsType<JobListing>(okResult.Value);
        Assert.Equal("apple-789", job.Id);
        Assert.Equal("Machine Learning Engineer", job.Title);
        Assert.Equal("apple", job.Company);
    }

    [Fact]
    public async Task GetJob_ReturnsNotFound_WhenMissing()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act
        var result = await controller.GetJob("nonexistent-id");

        // Assert
        Assert.IsType<NotFoundResult>(result.Result);
    }

    [Fact]
    public async Task GetJobs_CombinesCompanyAndPagination()
    {
        // Arrange
        var controller = new JobsController(_dbContext);

        // Act - Get 1 Apple job with offset
        var result = await controller.GetJobs(company: "apple", limit: 1, offset: 0);

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var jobs = Assert.IsAssignableFrom<IEnumerable<JobListing>>(okResult.Value);
        Assert.Single(jobs);
        Assert.Equal("apple", jobs.First().Company);
    }

    public void Dispose()
    {
        _dbContext.Dispose();
    }
}
