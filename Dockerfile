# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# Stage 1: dependency resolver
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Pull prebuilt uv binary from astral's image
COPY --from=ghcr.io/astral-sh/uv:0.6.0 /uv /bin/uv

WORKDIR /app

# Copy the lockfile + manifest first so this layer caches across code edits.
# The source is copied AFTER the sync so code edits don't invalidate the deps layer.
COPY pyproject.toml uv.lock README.md LICENSE ./

# Stub the package so `uv sync` has something to install as the root project.
RUN mkdir -p stays && echo "" > stays/__init__.py

# fastmcp + fastapi + pydantic-settings + uvicorn are core dependencies
# (since 0.1.0) so `uv sync` alone pulls everything the MCP server needs.
RUN uv sync --frozen --no-dev --no-cache

# Now copy the real source. Any code change invalidates only this layer.
COPY stays/ ./stays/

# -----------------------------------------------------------------------------
# Stage 2: minimal runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/stays /app/stays

ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"
ENV PYTHONUNBUFFERED=1
ENV HOST="0.0.0.0"
ENV PORT="8000"

EXPOSE 8000

# Run as non-root
RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

# Invariant: this exec-form CMD relies on the `stays` console script
# landing at /app/.venv/bin/stays. `uv sync` in the builder installs it
# because pyproject.toml declares `stays = "stays.cli._entry:run"` under
# [project.scripts]. The runtime stage inherits ENV PATH="/app/.venv/bin:$PATH"
# so a bare `stays` invocation resolves. If `stays` is ever dropped from
# [project.scripts], this breaks silently.
CMD ["stays", "mcp-http"]
