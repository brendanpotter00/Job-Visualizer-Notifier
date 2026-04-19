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

# Copy Alembic configuration and migration scripts.
# Must stay reachable at /app/alembic.ini + /app/alembic/ because
# src/backend/api/migrations.py resolves these via ALEMBIC_INI_PATH /
# Docker-layout fallback. See docs/implementations/alembicMigration/.
COPY alembic.ini ./
COPY src/backend/alembic/ ./alembic/

# Environment defaults
ENV PORT=8080
ENV PYTHONPATH=/app
ENV SCRAPER_SCRIPTS_PATH=/app/scripts
ENV SCRAPER_PYTHON_PATH=python3
EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
