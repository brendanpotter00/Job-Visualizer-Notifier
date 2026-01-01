namespace JobsApi.Data.Entities;

public class JobListing
{
    public string Id { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Company { get; set; } = string.Empty;
    public string? Location { get; set; }
    public string Url { get; set; } = string.Empty;
    public string SourceId { get; set; } = string.Empty;
    public string Details { get; set; } = "{}";
    public string CreatedAt { get; set; } = string.Empty;
    public string? PostedOn { get; set; }
    public string? ClosedOn { get; set; }
    public string Status { get; set; } = "OPEN";
    public bool HasMatched { get; set; }
    public string AiMetadata { get; set; } = "{}";
    public string FirstSeenAt { get; set; } = string.Empty;
    public string LastSeenAt { get; set; } = string.Empty;
    public int ConsecutiveMisses { get; set; }
    public bool DetailsScraped { get; set; }
}
