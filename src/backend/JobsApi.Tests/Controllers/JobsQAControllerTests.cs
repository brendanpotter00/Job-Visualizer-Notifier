using JobsApi.Controllers;
using JobsApi.Data.Entities;
using JobsApi.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace JobsApi.Tests.Controllers;

public class JobsQAControllerTests : IDisposable
{
    private readonly Mock<ScraperProcessRunner> _mockProcessRunner;
    private readonly Mock<ILogger<JobsQAController>> _mockLogger;
    private readonly JobsDbContext _dbContext;

    public JobsQAControllerTests()
    {
        _mockLogger = new Mock<ILogger<JobsQAController>>();

        // Create in-memory database for testing
        var options = new DbContextOptionsBuilder<JobsDbContext>()
            .UseInMemoryDatabase(databaseName: Guid.NewGuid().ToString())
            .Options;
        _dbContext = new JobsDbContext(options);

        // Mock the process runner (it has dependencies we don't want to set up)
        var mockConfig = new Mock<Microsoft.Extensions.Configuration.IConfiguration>();
        var mockRunnerLogger = new Mock<ILogger<ScraperProcessRunner>>();
        _mockProcessRunner = new Mock<ScraperProcessRunner>(mockConfig.Object, mockRunnerLogger.Object);
    }

    [Fact]
    public void TriggerScrape_Returns202Accepted()
    {
        // Arrange
        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        var result = controller.TriggerScrape("google");

        // Assert
        var acceptedResult = Assert.IsType<AcceptedResult>(result);
        Assert.NotNull(acceptedResult.Value);

        // Verify the response contains expected properties
        var responseValue = acceptedResult.Value;
        var messageProperty = responseValue.GetType().GetProperty("message");
        var companyProperty = responseValue.GetType().GetProperty("company");

        Assert.NotNull(messageProperty);
        Assert.NotNull(companyProperty);
        Assert.Equal("google", companyProperty.GetValue(responseValue));
        Assert.Contains("google", messageProperty.GetValue(responseValue)?.ToString());
    }

    [Fact]
    public void TriggerScrape_UsesDefaultCompanyWhenNotSpecified()
    {
        // Arrange
        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act - don't specify company, should default to "google"
        var result = controller.TriggerScrape();

        // Assert
        var acceptedResult = Assert.IsType<AcceptedResult>(result);
        var responseValue = acceptedResult.Value;
        var companyProperty = responseValue?.GetType().GetProperty("company");

        Assert.Equal("google", companyProperty?.GetValue(responseValue));
    }

    [Fact]
    public void TriggerScrape_LogsManualTrigger()
    {
        // Arrange
        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        controller.TriggerScrape("testcompany");

        // Assert - verify logging was called
        _mockLogger.Verify(
            x => x.Log(
                LogLevel.Information,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((v, t) => v.ToString()!.Contains("Manual scrape triggered")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }

    [Fact]
    public void TriggerScrape_AcceptsAnyCompanyName()
    {
        // Arrange
        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        var result = controller.TriggerScrape("custom-company-name");

        // Assert
        var acceptedResult = Assert.IsType<AcceptedResult>(result);
        var responseValue = acceptedResult.Value;
        var companyProperty = responseValue?.GetType().GetProperty("company");

        Assert.Equal("custom-company-name", companyProperty?.GetValue(responseValue));
    }

    [Fact]
    public void TriggerScrape_ResponseMessageContainsCompanyName()
    {
        // Arrange
        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        var result = controller.TriggerScrape("mycompany");

        // Assert
        var acceptedResult = Assert.IsType<AcceptedResult>(result);
        var responseValue = acceptedResult.Value;
        var messageProperty = responseValue?.GetType().GetProperty("message");
        var message = messageProperty?.GetValue(responseValue)?.ToString();

        Assert.Contains("mycompany", message);
        Assert.Contains("Scrape started", message);
    }

    [Fact]
    public void TriggerScrape_AcceptsAppleCompany()
    {
        // Arrange
        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        var result = controller.TriggerScrape("apple");

        // Assert
        var acceptedResult = Assert.IsType<AcceptedResult>(result);
        var responseValue = acceptedResult.Value;
        var companyProperty = responseValue?.GetType().GetProperty("company");

        Assert.Equal("apple", companyProperty?.GetValue(responseValue));
    }

    [Fact]
    public async Task GetStats_ReturnsStatsForAllCompanies()
    {
        // Arrange - seed some job data
        _dbContext.JobListings.AddRange(
            new JobListing
            {
                Id = "google-1",
                Title = "Software Engineer",
                Company = "google",
                Url = "https://google.com/job/1",
                SourceId = "google_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-01T00:00:00Z",
                FirstSeenAt = "2025-01-01T00:00:00Z",
                LastSeenAt = "2025-01-01T00:00:00Z"
            },
            new JobListing
            {
                Id = "google-2",
                Title = "Data Scientist",
                Company = "google",
                Url = "https://google.com/job/2",
                SourceId = "google_scraper",
                Status = "CLOSED",
                CreatedAt = "2025-01-01T00:00:00Z",
                FirstSeenAt = "2025-01-01T00:00:00Z",
                LastSeenAt = "2025-01-01T00:00:00Z"
            },
            new JobListing
            {
                Id = "apple-1",
                Title = "ML Engineer",
                Company = "apple",
                Url = "https://apple.com/job/1",
                SourceId = "apple_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-01T00:00:00Z",
                FirstSeenAt = "2025-01-01T00:00:00Z",
                LastSeenAt = "2025-01-01T00:00:00Z"
            }
        );
        await _dbContext.SaveChangesAsync();

        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        var result = await controller.GetStats();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var stats = Assert.IsType<JobsStats>(okResult.Value);

        Assert.Equal(3, stats.TotalJobs);
        Assert.Equal(2, stats.OpenJobs);
        Assert.Equal(1, stats.ClosedJobs);
        Assert.Equal(2, stats.CompanyCounts.Count);
        Assert.Contains(stats.CompanyCounts, c => c.Company == "google" && c.Count == 2);
        Assert.Contains(stats.CompanyCounts, c => c.Company == "apple" && c.Count == 1);
    }

    [Fact]
    public async Task GetStats_FiltersbyCompany_Apple()
    {
        // Arrange - seed some job data
        _dbContext.JobListings.AddRange(
            new JobListing
            {
                Id = "google-3",
                Title = "Software Engineer",
                Company = "google",
                Url = "https://google.com/job/3",
                SourceId = "google_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-01T00:00:00Z",
                FirstSeenAt = "2025-01-01T00:00:00Z",
                LastSeenAt = "2025-01-01T00:00:00Z"
            },
            new JobListing
            {
                Id = "apple-2",
                Title = "iOS Developer",
                Company = "apple",
                Url = "https://apple.com/job/2",
                SourceId = "apple_scraper",
                Status = "OPEN",
                CreatedAt = "2025-01-01T00:00:00Z",
                FirstSeenAt = "2025-01-01T00:00:00Z",
                LastSeenAt = "2025-01-01T00:00:00Z"
            },
            new JobListing
            {
                Id = "apple-3",
                Title = "Data Engineer",
                Company = "apple",
                Url = "https://apple.com/job/3",
                SourceId = "apple_scraper",
                Status = "CLOSED",
                CreatedAt = "2025-01-01T00:00:00Z",
                FirstSeenAt = "2025-01-01T00:00:00Z",
                LastSeenAt = "2025-01-01T00:00:00Z"
            }
        );
        await _dbContext.SaveChangesAsync();

        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act - filter by Apple only
        var result = await controller.GetStats(company: "apple");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var stats = Assert.IsType<JobsStats>(okResult.Value);

        Assert.Equal(2, stats.TotalJobs);  // Only Apple jobs
        Assert.Equal(1, stats.OpenJobs);
        Assert.Equal(1, stats.ClosedJobs);
        Assert.Single(stats.CompanyCounts);
        Assert.Equal("apple", stats.CompanyCounts[0].Company);
        Assert.Equal(2, stats.CompanyCounts[0].Count);
    }

    [Fact]
    public async Task GetScrapeRuns_ReturnsRunsForCompany()
    {
        // Arrange - seed scrape runs
        _dbContext.ScrapeRuns.AddRange(
            new ScrapeRun
            {
                RunId = "run-google-1",
                Company = "google",
                StartedAt = "2025-01-15T10:00:00Z",
                CompletedAt = "2025-01-15T10:30:00Z",
                Mode = "incremental",
                JobsSeen = 100,
                NewJobs = 10,
                ClosedJobs = 5
            },
            new ScrapeRun
            {
                RunId = "run-apple-1",
                Company = "apple",
                StartedAt = "2025-01-15T11:00:00Z",
                CompletedAt = "2025-01-15T11:45:00Z",
                Mode = "full",
                JobsSeen = 200,
                NewJobs = 50,
                ClosedJobs = 10
            },
            new ScrapeRun
            {
                RunId = "run-google-2",
                Company = "google",
                StartedAt = "2025-01-16T10:00:00Z",
                CompletedAt = "2025-01-16T10:30:00Z",
                Mode = "incremental",
                JobsSeen = 102,
                NewJobs = 2,
                ClosedJobs = 1
            }
        );
        await _dbContext.SaveChangesAsync();

        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act - get all runs
        var result = await controller.GetScrapeRuns();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var runs = Assert.IsAssignableFrom<IEnumerable<ScrapeRun>>(okResult.Value);
        Assert.Equal(3, runs.Count());
    }

    [Fact]
    public async Task GetScrapeRuns_FiltersbyCompany_Apple()
    {
        // Arrange - seed scrape runs
        _dbContext.ScrapeRuns.AddRange(
            new ScrapeRun
            {
                RunId = "run-google-3",
                Company = "google",
                StartedAt = "2025-01-15T10:00:00Z",
                Mode = "incremental",
                JobsSeen = 100
            },
            new ScrapeRun
            {
                RunId = "run-apple-2",
                Company = "apple",
                StartedAt = "2025-01-15T11:00:00Z",
                Mode = "full",
                JobsSeen = 200
            },
            new ScrapeRun
            {
                RunId = "run-apple-3",
                Company = "apple",
                StartedAt = "2025-01-16T11:00:00Z",
                Mode = "incremental",
                JobsSeen = 210
            }
        );
        await _dbContext.SaveChangesAsync();

        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act - filter by Apple only
        var result = await controller.GetScrapeRuns(company: "apple");

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var runs = Assert.IsAssignableFrom<IEnumerable<ScrapeRun>>(okResult.Value);
        Assert.Equal(2, runs.Count());
        Assert.All(runs, r => Assert.Equal("apple", r.Company));
    }

    [Fact]
    public async Task GetScrapeRuns_RespectsLimitParameter()
    {
        // Arrange - seed many scrape runs
        for (int i = 0; i < 30; i++)
        {
            _dbContext.ScrapeRuns.Add(new ScrapeRun
            {
                RunId = $"run-{i}",
                Company = "google",
                StartedAt = $"2025-01-{i + 1:D2}T10:00:00Z",
                Mode = "incremental",
                JobsSeen = 100 + i
            });
        }
        await _dbContext.SaveChangesAsync();

        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act - request only 5 runs
        var result = await controller.GetScrapeRuns(limit: 5);

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var runs = Assert.IsAssignableFrom<IEnumerable<ScrapeRun>>(okResult.Value);
        Assert.Equal(5, runs.Count());
    }

    [Fact]
    public async Task GetScrapeRuns_OrdersByStartedAtDescending()
    {
        // Arrange - seed scrape runs with different dates
        _dbContext.ScrapeRuns.AddRange(
            new ScrapeRun
            {
                RunId = "run-old",
                Company = "google",
                StartedAt = "2025-01-10T10:00:00Z",
                Mode = "full",
                JobsSeen = 100
            },
            new ScrapeRun
            {
                RunId = "run-new",
                Company = "google",
                StartedAt = "2025-01-16T10:00:00Z",
                Mode = "incremental",
                JobsSeen = 110
            },
            new ScrapeRun
            {
                RunId = "run-mid",
                Company = "google",
                StartedAt = "2025-01-13T10:00:00Z",
                Mode = "incremental",
                JobsSeen = 105
            }
        );
        await _dbContext.SaveChangesAsync();

        var controller = new JobsQAController(_dbContext, _mockProcessRunner.Object, _mockLogger.Object);

        // Act
        var result = await controller.GetScrapeRuns();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var runs = Assert.IsAssignableFrom<IEnumerable<ScrapeRun>>(okResult.Value).ToList();

        // Should be ordered newest first
        Assert.Equal("run-new", runs[0].RunId);
        Assert.Equal("run-mid", runs[1].RunId);
        Assert.Equal("run-old", runs[2].RunId);
    }

    public void Dispose()
    {
        _dbContext.Dispose();
    }
}
