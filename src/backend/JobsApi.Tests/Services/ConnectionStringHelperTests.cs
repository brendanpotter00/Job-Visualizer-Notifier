using JobsApi.Services;

namespace JobsApi.Tests.Services;

public class ConnectionStringHelperTests
{
    [Fact]
    public void ConvertToPostgresUrl_ValidConnectionString_ReturnsCorrectUrl()
    {
        // Arrange
        var connectionString = "Host=localhost;Port=5432;Database=jobscraper;Username=admin;Password=secret123";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Equal("postgresql://admin:secret123@localhost:5432/jobscraper", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_MissingPort_UsesDefaultPort()
    {
        // Arrange
        var connectionString = "Host=myhost.com;Database=mydb;Username=user;Password=pass";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Equal("postgresql://user:pass@myhost.com:5432/mydb", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_MissingHost_UsesLocalhost()
    {
        // Arrange
        var connectionString = "Database=mydb;Username=user;Password=pass";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Contains("@localhost:", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_WithSpaces_ParsesCorrectly()
    {
        // Arrange
        var connectionString = "Host = localhost ; Database = testdb ; Username = testuser ; Password = testpass";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Equal("postgresql://testuser:testpass@localhost:5432/testdb", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_PasswordWithEqualsSign_PreservesPassword()
    {
        // Arrange - password with = sign (split with limit 2 handles this)
        var connectionString = "Host=localhost;Database=db;Username=user;Password=p@ss=word";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Contains("p@ss=word", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_EmptyString_ReturnsDefaultValues()
    {
        // Arrange
        var connectionString = "";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Equal("postgresql://:@localhost:5432/", result);
    }

    [Fact]
    public void ConvertToPostgresUrl_CaseInsensitiveKeys_ParsesCorrectly()
    {
        // Arrange
        var connectionString = "HOST=myhost;DATABASE=mydb;USERNAME=myuser;PASSWORD=mypass;PORT=5433";

        // Act
        var result = ConnectionStringHelper.ConvertToPostgresUrl(connectionString);

        // Assert
        Assert.Equal("postgresql://myuser:mypass@myhost:5433/mydb", result);
    }
}
