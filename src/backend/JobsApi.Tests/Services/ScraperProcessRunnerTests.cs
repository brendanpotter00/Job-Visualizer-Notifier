using JobsApi.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;

namespace JobsApi.Tests.Services;

public class ScraperProcessRunnerTests
{
    private readonly Mock<ILogger<ScraperProcessRunner>> _mockLogger;
    private readonly ScraperProcessRunner _runner;

    public ScraperProcessRunnerTests()
    {
        _mockLogger = new Mock<ILogger<ScraperProcessRunner>>();

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

        _runner = new ScraperProcessRunner(configuration, _mockLogger.Object);
    }

    [Fact]
    public void IsScraperRunning_InitialState_ReturnsFalse()
    {
        // Act
        var isRunning = _runner.IsScraperRunning("google");

        // Assert
        Assert.False(isRunning);
    }

    [Fact]
    public void IsScraperRunning_UnknownCompany_ReturnsFalse()
    {
        // Act
        var isRunning = _runner.IsScraperRunning("unknown-company");

        // Assert
        Assert.False(isRunning);
    }

    [Fact]
    public void GetAllScraperStates_InitialState_ReturnsEmptyDictionary()
    {
        // Act
        var states = _runner.GetAllScraperStates();

        // Assert
        Assert.Empty(states);
    }

    [Fact]
    public async Task RunScraperAsync_ConcurrentCallsSameCompany_SecondCallRejected()
    {
        // Arrange - use a script path that doesn't exist so process fails quickly
        // but we can still test the semaphore behavior

        var cts = new CancellationTokenSource();
        var company = "google";

        // Start first scrape (will fail but that's OK - we're testing concurrency)
        var firstTask = _runner.RunScraperAsync(company, cts.Token);

        // Give it a moment to acquire the semaphore
        await Task.Delay(50);

        // Check state while running
        var isRunning = _runner.IsScraperRunning(company);

        // Start second scrape immediately - should be rejected
        var secondResult = await _runner.RunScraperAsync(company, cts.Token);

        // Wait for first to complete
        var firstResult = await firstTask;

        // Assert
        Assert.True(isRunning, "Scraper should be marked as running");
        Assert.Equal(-1, secondResult.ExitCode);
        Assert.Contains("already in progress", secondResult.Error);
    }

    [Fact]
    public async Task RunScraperAsync_DifferentCompanies_BothCanRun()
    {
        // Arrange
        var cts = new CancellationTokenSource();

        // Act - start scrapers for different companies
        var googleTask = _runner.RunScraperAsync("google", cts.Token);
        var metaTask = _runner.RunScraperAsync("meta", cts.Token);

        // Wait for both to complete
        var googleResult = await googleTask;
        var metaResult = await metaTask;

        // Assert - both should have attempted to run (not rejected)
        // They will fail due to missing scripts, but ExitCode -1 with "already in progress"
        // would indicate rejection, which we don't want
        Assert.DoesNotContain("already in progress", googleResult.Error);
        Assert.DoesNotContain("already in progress", metaResult.Error);
    }

    [Fact]
    public async Task RunScraperAsync_AfterCompletion_StateIsCleared()
    {
        // Arrange
        var cts = new CancellationTokenSource();
        var company = "google";

        // Act - run and wait for completion
        await _runner.RunScraperAsync(company, cts.Token);

        // Assert - state should be cleared
        var isRunning = _runner.IsScraperRunning(company);
        Assert.False(isRunning);

        var states = _runner.GetAllScraperStates();
        if (states.TryGetValue(company, out var state))
        {
            Assert.False(state.IsRunning);
        }
    }

    [Fact]
    public async Task RunScraperAsync_AfterCompletion_CanRunAgain()
    {
        // Arrange
        var cts = new CancellationTokenSource();
        var company = "google";

        // Act - run twice sequentially
        var firstResult = await _runner.RunScraperAsync(company, cts.Token);
        var secondResult = await _runner.RunScraperAsync(company, cts.Token);

        // Assert - second run should not be rejected
        Assert.DoesNotContain("already in progress", secondResult.Error);
    }

    [Fact]
    public async Task GetAllScraperStates_WhileRunning_ContainsRunningState()
    {
        // Arrange
        var cts = new CancellationTokenSource();
        var company = "google";

        // Start scrape
        var task = _runner.RunScraperAsync(company, cts.Token);

        // Give it a moment to start
        await Task.Delay(50);

        // Act
        var states = _runner.GetAllScraperStates();

        // Assert
        Assert.True(states.ContainsKey(company));
        Assert.True(states[company].IsRunning);
        Assert.NotNull(states[company].StartedAt);

        // Cleanup
        await task;
    }
}
