# PolicyFlow backend — powers the compose `api` and `worker` services.
# uv-managed Python 3.11 (matches pyproject `requires-python`/mypy target).
FROM python:3.11-slim

# uv: fast, reproducible installs from the committed uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# System libs Docling/Pillow/Tesseract need at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr libgl1 libglib2.0-0 poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install deps first (better layer caching) — only the manifests, not the source.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev || uv sync --no-install-project --no-dev

# App source + editable install of the project itself.
COPY . .
RUN uv sync --no-dev || true

# Runtime system libs, kept as a late layer so they don't invalidate the cached
# dependency layer above:
#   libpq5 — psycopg3 (LangGraph Postgres checkpointer)
#   g++    — torch's inductor backend that Docling's models compile through
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 g++ \
    && rm -rf /var/lib/apt/lists/*

# Put the uv venv on PATH so compose's bare `uvicorn`/`celery` commands resolve.
ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# Default is the API; the worker service overrides `command:` in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
