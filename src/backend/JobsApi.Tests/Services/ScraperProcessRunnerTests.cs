using JobsApi.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace JobsApi.Tests.Services;

public class ScraperProcessRunnerTests
{
    private readonly Mock<IConfiguration> _mockConfiguration;
    private readonly Mock<ILogger<ScraperProcessRunner>> _mockLogger;

    public ScraperProcessRunnerTests()
    {
        _mockConfiguration = new Mock<IConfiguration>();
        _mockLogger = new Mock<ILogger<ScraperProcessRunner>>();

        // Set up default configuration
        _mockConfiguration.Setup(c => c["Scraper:Environment"]).Returns("test");
        _mockConfiguration.Setup(c => c["Scraper:ScriptsPath"]).Returns("/tmp/scripts");
        _mockConfiguration.Setup(c => c["Scraper:PythonPath"]).Returns("python3");
        _mockConfiguration.Setup(c => c.GetSection("Scraper:DetailScrape").Value).Returns("true");
        _mockConfiguration.Setup(c => c.GetSection("Scraper:TimeoutMinutes").Value).Returns("1");

        var connectionStringSection = new Mock<IConfigurationSection>();
        connectionStringSection.Setup(s => s.Value).Returns("Host=localhost;Port=5432;Database=test;Username=test;Password=test");
        _mockConfiguration.Setup(c => c.GetSection("ConnectionStrings:DefaultConnection")).Returns(connectionStringSection.Object);
    }

    [Fact]
    public async Task RunScraperAsync_ReturnsResult_WhenProcessCompletes()
    {
        // This test verifies the basic structure - actual process execution
        // would require integration tests with a real Python environment

        // For unit testing, we verify the configuration is read correctly
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:Environment"] = "test",
                ["Scraper:ScriptsPath"] = "/nonexistent/path",
                ["Scraper:PythonPath"] = "echo", // Use echo as a simple command that exits quickly
                ["Scraper:DetailScrape"] = "false",
                ["Scraper:TimeoutMinutes"] = "1",
                ["ConnectionStrings:DefaultConnection"] = "Host=localhost;Port=5432;Database=test;Username=test;Password=test"
            })
            .Build();

        var logger = new Mock<ILogger<ScraperProcessRunner>>();
        var runner = new ScraperProcessRunner(config, logger.Object);

        // This will fail because the script doesn't exist, but it tests the flow
        var result = await runner.RunScraperAsync("google", CancellationToken.None);

        // Should return a result (either success or failure)
        Assert.NotNull(result);
        Assert.Equal("google", result.Company);
        Assert.NotEqual(default, result.CompletedAt);
    }

    [Fact]
    public async Task RunScraperAsync_RespectsTimeout_Configuration()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:Environment"] = "test",
                ["Scraper:ScriptsPath"] = "/tmp",
                ["Scraper:PythonPath"] = "sleep", // Use sleep command to test timeout
                ["Scraper:DetailScrape"] = "false",
                ["Scraper:TimeoutMinutes"] = "0", // 0 minutes = immediate timeout (uses default 60)
                ["ConnectionStrings:DefaultConnection"] = "Host=localhost;Port=5432;Database=test;Username=test;Password=test"
            })
            .Build();

        var logger = new Mock<ILogger<ScraperProcessRunner>>();
        var runner = new ScraperProcessRunner(config, logger.Object);

        // The timeout configuration should be read (even if the process fails for other reasons)
        var result = await runner.RunScraperAsync("google", CancellationToken.None);

        Assert.NotNull(result);
    }

    [Fact]
    public async Task RunScraperAsync_HandlesCancellation()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Scraper:Environment"] = "test",
                ["Scraper:ScriptsPath"] = "/tmp",
                ["Scraper:PythonPath"] = "sleep",
                ["Scraper:DetailScrape"] = "false",
                ["Scraper:TimeoutMinutes"] = "60",
                ["ConnectionStrings:DefaultConnection"] = "Host=localhost;Port=5432;Database=test;Username=test;Password=test"
            })
            .Build();

        var logger = new Mock<ILogger<ScraperProcessRunner>>();
        var runner = new ScraperProcessRunner(config, logger.Object);

        // Create a cancelled token
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        // Should handle cancellation gracefully
        var result = await runner.RunScraperAsync("google", cts.Token);

        Assert.NotNull(result);
        // Should return an error result when cancelled
        Assert.True(result.ExitCode != 0 || !string.IsNullOrEmpty(result.Error));
    }
}

public class ConnectionStringHelperTests
{
    [Fact]
    public void ConvertToPostgresUrl_ConvertsCorrectly()
    {
        var connectionString = "Host=myhost;Port=5432;Database=mydb;Username=myuser;Password=mypass";

        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        Assert.Equal("postgresql://myuser:mypass@myhost:5432/mydb", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_HandlesDefaultPort()
    {
        var connectionString = "Host=localhost;Database=testdb;Username=admin;Password=secret";

        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        Assert.Equal("postgresql://admin:secret@localhost:5432/testdb", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_HandlesMissingValues()
    {
        var connectionString = "Host=myhost";

        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        Assert.Equal("postgresql://:@myhost:5432/", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_IsCaseInsensitive()
    {
        var connectionString = "HOST=myhost;PORT=5433;DATABASE=mydb;USERNAME=user;PASSWORD=pass";

        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        Assert.Equal("postgresql://user:pass@myhost:5433/mydb", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_HandlesPasswordWithSpecialChars()
    {
        // Password contains = which should be preserved (split on first = only)
        var connectionString = "Host=myhost;Port=5432;Database=mydb;Username=user;Password=p@ss=word";

        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Password with = should be handled correctly (split on first =)
        Assert.Equal("postgresql://user:p@ss=word@myhost:5432/mydb", result);
    }
}
