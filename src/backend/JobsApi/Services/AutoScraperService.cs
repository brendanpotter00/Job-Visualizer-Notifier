namespace JobsApi.Services;

public class AutoScraperService(
    ScraperProcessRunner processRunner,
    ILogger<AutoScraperService> logger)
    : BackgroundService
{
    private readonly TimeSpan _interval = TimeSpan.FromHours(1);
    private readonly string[] _companies = ["google"];

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await Task.Delay(TimeSpan.FromSeconds(10), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            foreach (var company in _companies)
            {
                logger.LogInformation("Starting scrape for {Company}", company);
                await processRunner.RunScraperAsync(company, stoppingToken);
            }
            await Task.Delay(_interval, stoppingToken);
        }
    }
}
