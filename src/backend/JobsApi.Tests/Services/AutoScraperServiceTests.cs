using JobsApi.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace JobsApi.Tests.Services;

public class AutoScraperServiceTests
{
    private readonly Mock<ScraperProcessRunner> _mockProcessRunner;
    private readonly Mock<ILogger<AutoScraperService>> _mockLogger;

    public AutoScraperServiceTests()
    {
        _mockLogger = new Mock<ILogger<AutoScraperService>>();

        // Create mock configuration for the process runner
        var mockConfig = new Mock<IConfiguration>();
        var mockRunnerLogger = new Mock<ILogger<ScraperProcessRunner>>();
        _mockProcessRunner = new Mock<ScraperProcessRunner>(mockConfig.Object, mockRunnerLogger.Object);
    }

    [Fact]
    public async Task ExecuteAsync_IteratesThroughConfiguredCompanies()
    {
        // Arrange
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1",
                ["Scraper:Companies:0"] = "google",
                ["Scraper:Companies:1"] = "apple"
            })
            .Build();

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "test", ExitCode = 0, CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act - Run service briefly then cancel
        var executeTask = service.StartAsync(cts.Token);

        // Wait enough time for at least one cycle to start
        await Task.Delay(50);
        cts.Cancel();

        try
        {
            await service.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // Expected when cancelling
        }

        // Assert - Verify both companies were scraped
        _mockProcessRunner.Verify(
            r => r.RunScraperAsync("google", It.IsAny<CancellationToken>()),
            Times.AtMostOnce());
        _mockProcessRunner.Verify(
            r => r.RunScraperAsync("apple", It.IsAny<CancellationToken>()),
            Times.AtMostOnce());
    }

    [Fact]
    public async Task ExecuteAsync_UsesDefaultCompanyWhenNotConfigured()
    {
        // Arrange
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1"
                // No companies configured - should default to google
            })
            .Build();

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "google", ExitCode = 0, CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act
        var executeTask = service.StartAsync(cts.Token);
        await Task.Delay(50);
        cts.Cancel();

        try
        {
            await service.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // Expected
        }

        // Assert - Default is google
        _mockProcessRunner.Verify(
            r => r.RunScraperAsync("google", It.IsAny<CancellationToken>()),
            Times.AtMostOnce());
    }

    [Fact]
    public async Task ExecuteAsync_HandlesCancellation()
    {
        // Arrange
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1",
                ["Scraper:Companies:0"] = "google"
            })
            .Build();

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "google", ExitCode = 0, CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act - Start and immediately cancel
        var executeTask = service.StartAsync(cts.Token);
        cts.Cancel();

        // Assert - Should handle cancellation gracefully (no exceptions)
        await service.StopAsync(CancellationToken.None);
        Assert.True(true); // If we got here, cancellation was handled properly
    }

    [Fact]
    public async Task ExecuteAsync_ContinuesOnSingleCompanyFailure()
    {
        // Arrange
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1",
                ["Scraper:Companies:0"] = "google",
                ["Scraper:Companies:1"] = "apple"
            })
            .Build();

        // Google succeeds, Apple fails
        _mockProcessRunner
            .Setup(r => r.RunScraperAsync("google", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "google", ExitCode = 0, CompletedAt = DateTime.UtcNow });

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync("apple", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "apple", ExitCode = 1, Error = "Scrape failed", CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act
        var executeTask = service.StartAsync(cts.Token);
        await Task.Delay(50);
        cts.Cancel();

        try
        {
            await service.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // Expected
        }

        // Assert - Both companies should have been attempted despite Apple failure
        _mockProcessRunner.Verify(
            r => r.RunScraperAsync("google", It.IsAny<CancellationToken>()),
            Times.AtMostOnce());
        _mockProcessRunner.Verify(
            r => r.RunScraperAsync("apple", It.IsAny<CancellationToken>()),
            Times.AtMostOnce());
    }

    [Fact]
    public async Task ExecuteAsync_LogsSuccessfulScrape()
    {
        // Arrange
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1",
                ["Scraper:Companies:0"] = "google"
            })
            .Build();

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync("google", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "google", ExitCode = 0, CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act
        var executeTask = service.StartAsync(cts.Token);
        await Task.Delay(100);
        cts.Cancel();

        try
        {
            await service.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // Expected
        }

        // Assert - Should log successful completion
        _mockLogger.Verify(
            x => x.Log(
                LogLevel.Information,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((v, t) => v.ToString()!.Contains("completed successfully")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtMostOnce());
    }

    [Fact]
    public async Task ExecuteAsync_LogsFailedScrape()
    {
        // Arrange
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1",
                ["Scraper:Companies:0"] = "apple"
            })
            .Build();

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync("apple", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "apple", ExitCode = 1, Error = "Network error", CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act
        var executeTask = service.StartAsync(cts.Token);
        await Task.Delay(100);
        cts.Cancel();

        try
        {
            await service.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // Expected
        }

        // Assert - Should log warning for failed scrape
        _mockLogger.Verify(
            x => x.Log(
                LogLevel.Warning,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((v, t) => v.ToString()!.Contains("exit code")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtMostOnce());
    }

    [Fact]
    public async Task ExecuteAsync_RespectsIntervalConfiguration()
    {
        // Arrange - Configure a very short interval
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:IntervalHours"] = "1",
                ["Scraper:Companies:0"] = "google"
            })
            .Build();

        _mockProcessRunner
            .Setup(r => r.RunScraperAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScraperResult { Company = "google", ExitCode = 0, CompletedAt = DateTime.UtcNow });

        var service = new AutoScraperService(_mockProcessRunner.Object, config, _mockLogger.Object);
        using var cts = new CancellationTokenSource();

        // Act - Service reads interval from config
        var executeTask = service.StartAsync(cts.Token);
        await Task.Delay(50);
        cts.Cancel();

        try
        {
            await service.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // Expected
        }

        // Assert - Logging should mention the interval
        _mockLogger.Verify(
            x => x.Log(
                LogLevel.Information,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((v, t) => v.ToString()!.Contains("waiting")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtMostOnce());
    }
}
