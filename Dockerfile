FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Copy source
COPY app/ app/
COPY prompts/ prompts/
COPY knowledge/ knowledge/
COPY main.py .

# Install the project entry point
RUN uv sync --no-dev --frozen

CMD ["uv", "run", "rovebot"]
