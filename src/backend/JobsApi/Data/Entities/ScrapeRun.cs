namespace JobsApi.Data.Entities;

public class ScrapeRun
{
    public string RunId { get; set; } = string.Empty;
    public string Company { get; set; } = string.Empty;
    public string StartedAt { get; set; } = string.Empty;
    public string? CompletedAt { get; set; }
    public string Mode { get; set; } = string.Empty;
    public int JobsSeen { get; set; }
    public int NewJobs { get; set; }
    public int ClosedJobs { get; set; }
    public int DetailsFetched { get; set; }
    public int ErrorCount { get; set; }
}
