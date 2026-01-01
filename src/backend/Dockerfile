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

# Create startup script
RUN echo '#!/bin/bash' > /app/start.sh && \
    echo 'echo "=== CONTAINER STARTING ==="' >> /app/start.sh && \
    echo 'echo "DATE: $(date)"' >> /app/start.sh && \
    echo 'echo "HOSTNAME: $(hostname)"' >> /app/start.sh && \
    echo 'echo "ASPNETCORE_URLS: $ASPNETCORE_URLS"' >> /app/start.sh && \
    echo 'echo "PWD: $(pwd)"' >> /app/start.sh && \
    echo 'ls -la' >> /app/start.sh && \
    echo 'echo "=== Starting dotnet ==="' >> /app/start.sh && \
    echo 'exec dotnet JobsApi.dll' >> /app/start.sh && \
    chmod +x /app/start.sh

ENTRYPOINT ["/app/start.sh"]
