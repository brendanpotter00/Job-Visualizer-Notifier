FROM python:3.13-slim

WORKDIR /app

# Install API dependencies
COPY src/backend/api/requirements.txt ./api-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt

# Install scraper dependencies
COPY scripts/requirements.txt ./scripts-requirements.txt
RUN pip install --no-cache-dir -r scripts-requirements.txt

# Install Playwright chromium with ALL system dependencies.
# The --with-deps flag is required on slim base images (python:3.13-slim)
# which lack the system libraries Chromium needs for rendering heavy pages.
RUN playwright install --with-deps chromium

# Copy API code
COPY src/backend/api/ ./api/

# Copy scraper scripts
COPY scripts/ ./scripts/

# Environment defaults
ENV PORT=8080
ENV PYTHONPATH=/app
ENV SCRAPER_SCRIPTS_PATH=/app/scripts
ENV SCRAPER_PYTHON_PATH=python3

# Use glibc malloc instead of pymalloc so freed memory returns to OS
ENV PYTHONMALLOC=malloc
ENV MALLOC_TRIM_THRESHOLD_=65536
ENV MALLOC_MMAP_THRESHOLD_=65536

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
