using System.Diagnostics;

namespace JobsApi.Services;

public class ScraperProcessRunner(
    IConfiguration configuration,
    ILogger<ScraperProcessRunner> logger)
{
    public async Task<ScraperResult> RunScraperAsync(string company, CancellationToken cancellationToken)
    {
        var env = configuration["Scraper:Environment"] ?? "local";
        var dbUrl = ConnectionStringHelper.ConvertToPostgresUrl(configuration.GetConnectionString("DefaultConnection") ?? "");
        var scriptsPath = configuration["Scraper:ScriptsPath"] ?? "../../../scripts";
        var pythonPath = configuration["Scraper:PythonPath"] ?? "python3";
        var detailScrape = configuration.GetValue<bool>("Scraper:DetailScrape", true);

        var detailScrapeFlag = detailScrape ? " --detail-scrape" : "";
        var arguments = $"{scriptsPath}/run_scraper.py --company {company} --env {env} --db-url \"{dbUrl}\" --incremental --headless{detailScrapeFlag}";

        logger.LogInformation("Running scraper: {PythonPath} {Arguments}", pythonPath, arguments);

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonPath,
            Arguments = arguments,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using var process = new Process { StartInfo = startInfo };

        try
        {
            process.Start();

            var stdout = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            var stderr = await process.StandardError.ReadToEndAsync(cancellationToken);

            await process.WaitForExitAsync(cancellationToken);

            logger.LogInformation("Scraper exited with code {ExitCode}", process.ExitCode);

            return new ScraperResult
            {
                ExitCode = process.ExitCode,
                Output = stdout,
                Error = stderr,
                Company = company,
                CompletedAt = DateTime.UtcNow
            };
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to run scraper for {Company}", company);

            return new ScraperResult
            {
                ExitCode = -1,
                Output = "",
                Error = ex.Message,
                Company = company,
                CompletedAt = DateTime.UtcNow
            };
        }
    }
}

public class ScraperResult
{
    public int ExitCode { get; set; }
    public string Output { get; set; } = string.Empty;
    public string Error { get; set; } = string.Empty;
    public string Company { get; set; } = string.Empty;
    public DateTime CompletedAt { get; set; }
}

public static class ConnectionStringHelper
{
    public static string ConvertToPostgresUrl(string connectionString)
    {
        // Parse ADO.NET format: Host=x;Port=y;Database=z;Username=u;Password=p
        var parts = connectionString.Split(';')
            .Select(p => p.Split('=', 2))
            .Where(p => p.Length == 2)
            .ToDictionary(p => p[0].Trim(), p => p[1].Trim(), StringComparer.OrdinalIgnoreCase);

        var host = parts.GetValueOrDefault("Host", "localhost");
        var port = parts.GetValueOrDefault("Port", "5432");
        var database = parts.GetValueOrDefault("Database", "");
        var username = parts.GetValueOrDefault("Username", "");
        var password = parts.GetValueOrDefault("Password", "");

        return $"postgresql://{username}:{password}@{host}:{port}/{database}";
    }
}
