namespace JobsApi.Services;

public class AutoScraperService(
    ScraperProcessRunner processRunner,
    IConfiguration configuration,
    ILogger<AutoScraperService> logger)
    : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var intervalHours = configuration.GetValue<int>("Scraper:IntervalHours", 1);
        var companies = configuration.GetSection("Scraper:Companies").Get<string[]>() ?? ["google"];
        var interval = TimeSpan.FromHours(intervalHours);

        await Task.Delay(TimeSpan.FromSeconds(10), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            foreach (var company in companies)
            {
                logger.LogInformation("Starting scrape for {Company}", company);
                var result = await processRunner.RunScraperAsync(company, stoppingToken);

                if (result.ExitCode == 0)
                    logger.LogInformation("Scrape completed successfully for {Company}", company);
                else
                    logger.LogWarning("Scrape finished with exit code {ExitCode} for {Company}: {Error}",
                        result.ExitCode, company, result.Error);
            }

            logger.LogInformation("Scrape cycle complete, waiting {Interval} before next run", interval);
            await Task.Delay(interval, stoppingToken);
        }
    }
}
