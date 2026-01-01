using Microsoft.EntityFrameworkCore;

namespace JobsApi.Data.Entities;

public class JobsDbContext : DbContext
{
    private readonly string _environment;

    public DbSet<JobListing> JobListings => Set<JobListing>();
    public DbSet<ScrapeRun> ScrapeRuns => Set<ScrapeRun>();

    public JobsDbContext(DbContextOptions<JobsDbContext> options, IConfiguration configuration)
        : base(options)
    {
        _environment = configuration["Scraper:Environment"] ?? "local";
    }

    // Constructor for design-time (migrations)
    public JobsDbContext(DbContextOptions<JobsDbContext> options)
        : base(options)
    {
        _environment = "local";
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Dynamic table naming based on environment
        var jobListingsTable = $"job_listings_{_environment}";
        var scrapeRunsTable = $"scrape_runs_{_environment}";

        // JobListing configuration
        modelBuilder.Entity<JobListing>(entity =>
        {
            entity.ToTable(jobListingsTable);
            entity.HasKey(e => e.Id);

            entity.Property(e => e.Id).IsRequired();
            entity.Property(e => e.Title).IsRequired();
            entity.Property(e => e.Company).IsRequired();
            entity.Property(e => e.Url).IsRequired();
            entity.Property(e => e.SourceId).IsRequired();
            entity.Property(e => e.Details).HasDefaultValue("{}");
            entity.Property(e => e.Status).HasDefaultValue("OPEN");
            entity.Property(e => e.AiMetadata).HasDefaultValue("{}");
            entity.Property(e => e.ConsecutiveMisses).HasDefaultValue(0);
            entity.Property(e => e.HasMatched).HasDefaultValue(false);
            entity.Property(e => e.DetailsScraped).HasDefaultValue(false);

            // Indexes for common queries
            entity.HasIndex(e => e.Status);
            entity.HasIndex(e => e.Company);
            entity.HasIndex(e => e.LastSeenAt);
        });

        // ScrapeRun configuration
        modelBuilder.Entity<ScrapeRun>(entity =>
        {
            entity.ToTable(scrapeRunsTable);
            entity.HasKey(e => e.RunId);

            entity.Property(e => e.RunId).IsRequired();
            entity.Property(e => e.Company).IsRequired();
            entity.Property(e => e.StartedAt).IsRequired();
            entity.Property(e => e.Mode).IsRequired();
            entity.Property(e => e.JobsSeen).HasDefaultValue(0);
            entity.Property(e => e.NewJobs).HasDefaultValue(0);
            entity.Property(e => e.ClosedJobs).HasDefaultValue(0);
            entity.Property(e => e.DetailsFetched).HasDefaultValue(0);
            entity.Property(e => e.ErrorCount).HasDefaultValue(0);

            // Index for querying by company
            entity.HasIndex(e => e.Company);
        });
    }
}

// Extension method for registering DbContext with DI
public static class JobsDbContextExtensions
{
    public static IServiceCollection AddJobsDbContext(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        var connectionString = Environment.GetEnvironmentVariable("DATABASE_URL");

        if (!string.IsNullOrEmpty(connectionString) && connectionString.StartsWith("postgresql://"))
        {
            // Convert URL format to ADO.NET format for production
            connectionString = ConvertPostgresUrlToConnectionString(connectionString);
        }
        else
        {
            connectionString = configuration.GetConnectionString("DefaultConnection");
        }

        services.AddDbContext<JobsDbContext>(options =>
        {
            options.UseNpgsql(connectionString)
                   .UseSnakeCaseNamingConvention();
        });

        return services;
    }

    private static string ConvertPostgresUrlToConnectionString(string url)
    {
        var uri = new Uri(url);
        var userInfo = uri.UserInfo.Split(':');
        var username = userInfo[0];
        var password = userInfo.Length > 1 ? userInfo[1] : "";
        var host = uri.Host;
        var port = uri.Port > 0 ? uri.Port : 5432;
        var database = uri.AbsolutePath.TrimStart('/');

        return $"Host={host};Port={port};Database={database};Username={username};Password={password}";
    }
}
