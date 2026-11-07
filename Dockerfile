FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM python:3.11-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python3.11

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY --from=build /app/.venv /app/.venv
COPY --chown=app:app src/ ./src/
COPY --chown=app:app web/ ./web/
USER app
EXPOSE 8081
CMD ["python", "-m", "src.agent", "start"]
