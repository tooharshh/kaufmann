FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM python:3.11-slim-bookworm

COPY --from=uv /uv /uvx /usr/local/bin/
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python3.11

COPY --chown=app:app src/ ./src/
USER app

CMD ["python", "src/agent.py", "start"]
