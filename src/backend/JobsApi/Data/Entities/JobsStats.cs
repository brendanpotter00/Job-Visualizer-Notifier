namespace JobsApi.Data.Entities;

public class JobsStats
{
    public int TotalJobs { get; set; }
    public int OpenJobs { get; set; }
    public int ClosedJobs { get; set; }
    public List<CompanyCount> CompanyCounts { get; set; } = [];
}

public class CompanyCount
{
    public string Company { get; set; } = string.Empty;
    public int Count { get; set; }
}
