FROM python:3.13-slim

# Playwright browser dependencies
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install API dependencies
COPY src/backend/api/requirements.txt ./api-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt

# Install scraper dependencies
COPY scripts/requirements.txt ./scripts-requirements.txt
RUN pip install --no-cache-dir -r scripts-requirements.txt

# Install Playwright chromium
RUN playwright install chromium

# Copy API code
COPY src/backend/api/ ./api/

# Copy scraper scripts
COPY scripts/ ./scripts/

# Environment defaults
ENV PORT=8080
ENV PYTHONPATH=/app
ENV SCRAPER_SCRIPTS_PATH=/app/scripts
ENV SCRAPER_PYTHON_PATH=python3

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
