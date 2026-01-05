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

    public void Dispose()
    {
        _dbContext.Dispose();
    }
}
