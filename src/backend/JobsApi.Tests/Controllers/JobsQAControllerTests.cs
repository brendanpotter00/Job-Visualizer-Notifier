using JobsApi.Controllers;
using JobsApi.Data.Entities;
using JobsApi.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;

namespace JobsApi.Tests.Controllers;

public class JobsQAControllerTests : IDisposable
{
    private readonly Mock<ILogger<JobsQAController>> _mockLogger;
    private readonly Mock<ILogger<ScraperProcessRunner>> _mockRunnerLogger;
    private readonly ScraperProcessRunner _processRunner;
    private readonly JobsDbContext _dbContext;
    private readonly JobsQAController _controller;

    public JobsQAControllerTests()
    {
        _mockLogger = new Mock<ILogger<JobsQAController>>();
        _mockRunnerLogger = new Mock<ILogger<ScraperProcessRunner>>();

        // Use real in-memory configuration for proper GetConnectionString support
        // Use 'sleep' command to simulate a slow-running scraper for concurrency tests
        var configData = new Dictionary<string, string?>
        {
            ["Scraper:Environment"] = "test",
            ["Scraper:ScriptsPath"] = "-c \"import time; time.sleep(0.5)\" #",
            ["Scraper:PythonPath"] = "python3",
            ["Scraper:DetailScrape"] = "false",
            ["ConnectionStrings:DefaultConnection"] = "Host=localhost;Database=test;Username=user;Password=pass"
        };

        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(configData)
            .Build();

        _processRunner = new ScraperProcessRunner(configuration, _mockRunnerLogger.Object);

        // Use in-memory database for testing
        var options = new DbContextOptionsBuilder<JobsDbContext>()
            .UseInMemoryDatabase(databaseName: Guid.NewGuid().ToString())
            .Options;
        _dbContext = new JobsDbContext(options);

        _controller = new JobsQAController(_dbContext, _processRunner, _mockLogger.Object);
    }

    [Fact]
    public void GetScraperStatus_InitialState_ReturnsEmptyDictionary()
    {
        // Act
        var result = _controller.GetScraperStatus();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var states = Assert.IsAssignableFrom<IReadOnlyDictionary<string, ScraperState>>(okResult.Value);
        Assert.Empty(states);
    }

    [Fact]
    public async Task TriggerScrape_WhenNotRunning_StartsScraperAndReturnsOk()
    {
        // Arrange
        var cts = new CancellationTokenSource();

        // Act
        var result = await _controller.TriggerScrape("testcompany", cts.Token);

        // Assert - should return OK (even if scraper fails due to missing scripts)
        // The point is it wasn't rejected as "already in progress"
        Assert.IsNotType<ConflictObjectResult>(result.Result);
    }

    [Fact]
    public async Task TriggerScrape_WhenAlreadyRunning_ReturnsConflict()
    {
        // Arrange
        var cts = new CancellationTokenSource();
        var company = "google";

        // Start a scrape directly via the process runner to simulate running state
        var runningTask = _processRunner.RunScraperAsync(company, cts.Token);

        // Give it a moment to acquire semaphore
        await Task.Delay(50);

        // Act - try to trigger another scrape via controller
        var result = await _controller.TriggerScrape(company, cts.Token);

        // Assert
        var conflictResult = Assert.IsType<ConflictObjectResult>(result.Result);
        Assert.NotNull(conflictResult.Value);

        // Cleanup
        await runningTask;
    }

    [Fact]
    public async Task TriggerScrape_DifferentCompany_DoesNotConflict()
    {
        // Arrange
        var cts = new CancellationTokenSource();

        // Start a scrape for google
        var googleTask = _processRunner.RunScraperAsync("google", cts.Token);

        // Give it a moment
        await Task.Delay(50);

        // Act - try to trigger scrape for different company
        var result = await _controller.TriggerScrape("meta", cts.Token);

        // Assert - should not be a conflict
        Assert.IsNotType<ConflictObjectResult>(result.Result);

        // Cleanup
        await googleTask;
    }

    [Fact]
    public async Task GetScraperStatus_WhileRunning_ShowsRunningState()
    {
        // Arrange
        var cts = new CancellationTokenSource();
        var company = "google";

        // Start a scrape
        var task = _processRunner.RunScraperAsync(company, cts.Token);

        // Give it a moment
        await Task.Delay(50);

        // Act
        var result = _controller.GetScraperStatus();

        // Assert
        var okResult = Assert.IsType<OkObjectResult>(result.Result);
        var states = Assert.IsAssignableFrom<IReadOnlyDictionary<string, ScraperState>>(okResult.Value);
        Assert.True(states.ContainsKey(company));
        Assert.True(states[company].IsRunning);

        // Cleanup
        await task;
    }

    public void Dispose()
    {
        _dbContext.Dispose();
    }
}
