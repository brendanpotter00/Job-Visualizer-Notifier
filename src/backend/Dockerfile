# Base image with Python + .NET runtime
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base

# Install Python and Playwright dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    # Playwright browser dependencies
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Setup Python virtual environment and install dependencies
COPY scripts/requirements.txt ./scripts/
RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --upgrade pip && \
    /app/venv/bin/pip install -r scripts/requirements.txt && \
    /app/venv/bin/playwright install chromium

# Build .NET app
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY src/backend/JobsApi/ ./JobsApi/
RUN dotnet publish JobsApi/JobsApi.csproj -c Release -o /app/publish

# Final image
FROM base AS final
WORKDIR /app

# Copy .NET app
COPY --from=build /app/publish .

# Copy Python scripts
COPY scripts/ ./scripts/

# Environment variables
ENV ASPNETCORE_URLS=http://+:8080
ENV PATH="/app/venv/bin:$PATH"

EXPOSE 8080

# Debug: Print environment and start app
ENTRYPOINT ["/bin/bash", "-c", "echo '=== CONTAINER STARTING ===' && echo \"DATE: $(date)\" && echo \"HOSTNAME: $(hostname)\" && echo \"ASPNETCORE_URLS: $ASPNETCORE_URLS\" && echo 'PORT: 8080' && echo '=== Starting dotnet ===' && exec dotnet JobsApi.dll"]
