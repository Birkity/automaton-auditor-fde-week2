# Swarm Auditor — Digital Courtroom
# Multi-stage Dockerfile for containerized runtime

FROM python:3.13-slim AS base

# Install system dependencies for git operations and PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source
COPY rubric.json ./
COPY src/ ./src/
COPY app.py run_audit.py ./
COPY .env.example ./.env

# Create audit output directories
RUN mkdir -p audit/report_onself_generated \
             audit/report_onpeer_generated \
             audit/report_bypeer_received

# Expose Streamlit port
EXPOSE 8501

# Default: run the Streamlit UI
CMD ["uv", "run", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
