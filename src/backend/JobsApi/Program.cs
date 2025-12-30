using JobsApi.Data.Entities;
using JobsApi.Services;

var builder = WebApplication.CreateBuilder(args);

// Add DbContext with SQLite/PostgreSQL support
builder.Services.AddJobsDbContext(builder.Configuration);

// Add services
builder.Services.AddSingleton<ScraperProcessRunner>();
builder.Services.AddHostedService<AutoScraperService>();

// Add controllers
builder.Services.AddControllers();

// Add Swagger for API documentation
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// Configure middleware
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();

// Map controllers
app.MapControllers();

// Health check endpoint
app.MapGet("/health", () => "OK");

app.Run();
