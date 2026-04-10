FROM python:3.11-slim-bookworm

WORKDIR /app

# System deps:
#  - libpango/cairo/gdk-pixbuf — weasyprint (PDF reports)
#  - curl — used by Fly.io health checks and debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev libcairo2 curl && \
    rm -rf /var/lib/apt/lists/*

# Copy the bits needed to resolve the package install BEFORE running pip,
# so that editable-install path resolution finds the real ``src/`` tree.
# (Dev deps are included because ``alembic`` is listed under [project.dependencies]
# but the rest of the tool uses the dev extras as well.)
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[dev]"

# Copy the rest of the repo (alembic migrations, config files, etc.).
COPY . .

EXPOSE 8000

# Default CMD runs the FastAPI dashboard via uvicorn. Fly.io's web process
# uses this; one-shot jobs (run-cycle, daily-report, etc.) override it via
# `fly machine run` or by passing a different command at the CLI.
CMD ["uvicorn", "src.dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
