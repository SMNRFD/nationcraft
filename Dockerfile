FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates tini libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY game ./game
COPY locales ./locales

ENV PYTHONPATH=/app/src
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command runs API + worker (override per service in compose)
CMD ["python", "-m", "nationcraft.cli", "api"]
