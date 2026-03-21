# Multi-stage Dockerfile for Network Synapse Temporal worker
# Build: docker build -f development/Dockerfile -t synapse-worker .

# ---------------------------------------------------------------------------
# Stage 1: Base — Python + uv + system dependencies
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# ---------------------------------------------------------------------------
# Stage 2: Dependencies — install Python packages
# ---------------------------------------------------------------------------
FROM base AS dependencies

# Copy only dependency files first (cache layer)
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/
COPY workers/pyproject.toml workers/

# Install dependencies (without the project itself)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# ---------------------------------------------------------------------------
# Stage 3: Application — copy source and install project
# ---------------------------------------------------------------------------
FROM dependencies AS application

# Copy full source
COPY backend/ backend/
COPY workers/ workers/

# Install the project packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# ---------------------------------------------------------------------------
# Stage 4: Runtime — minimal final image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy the virtual environment from the build stage
COPY --from=application /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code
COPY --from=application /app/backend/ backend/
COPY --from=application /app/workers/ workers/

CMD ["python", "-m", "synapse_workers.worker"]
