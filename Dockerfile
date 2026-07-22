FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY prompts ./prompts
RUN uv sync --locked --no-dev --no-editable

RUN useradd --create-home --uid 10001 biasradar && chown -R biasradar:biasradar /app
USER biasradar

CMD ["biasradar", "worker"]
