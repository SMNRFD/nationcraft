FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates tini libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the entire project so hatchling has the source tree to build
# the package metadata. Then install in editable-free mode (wheel build).
COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY game ./game
COPY locales ./locales
COPY plugins ./plugins
COPY README.md ./README.md

RUN pip install --upgrade pip && pip install .

ENV PYTHONPATH=/app/src
EXPOSE 8000

# Healthcheck: hit the readiness endpoint every 30s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/health/live', timeout=3); sys.exit(0)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command runs API (override per service in compose)
CMD ["python", "-m", "nationcraft.cli", "api"]
