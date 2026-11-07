# Kaufmann

An English/Telugu voice shopping assistant with a conventional e-commerce storefront. Supports mixed-language discovery, product comparison, catalog filters, persisted carts, delivery addresses, profiles, order history and explicit demo-order confirmation.

The stack is Python 3.11, LiveKit Agents, Cerebras GPT-OSS 120B, Sarvam STT/Bulbul TTS, and Supabase PostgreSQL/Auth. The frontend uses native HTML/CSS/JavaScript with a bundled LiveKit browser SDK. No Node build is needed.

## Run locally

```sh
uv sync --locked
cp -n .env.example .env
```

Fill in `.env` with existing service credentials. Never commit it. Start the API and voice worker in separate terminals:

```sh
uv run python -m src.api
uv run python -m src.agent dev
```

Open http://localhost:8080, sign in and select the microphone. Localhost or HTTPS is required for microphone access. Use `python -m src.agent start` in production; the legacy `dev` command in the pinned SDK does not hot-reload.

## Production build

```sh
docker compose config --quiet
docker compose build
docker compose up -d
```

The same non-root image runs the API and voice worker separately. Compose publishes only the API on localhost; use HTTPS termination for public hosting. No migrations, seeding or model experiments run at startup. See [production instructions](docs/production.md) for health checks, graceful shutdown and Render configuration. These commands build and run containers; they do not provision Render.

## Verify

```sh
uv run ruff check .
uv run pytest
bash scripts/test_database.sh
```

The database script uses disposable PostgreSQL. Never point tests at a shared database. Browser and optional real-provider checks are described in [tests](tests/README.md) and [voice](docs/voice.md).

`uv run python -m src.check_connections` checks Cerebras model listing, Supabase Auth, LiveKit and a read-only database connection. It does not generate speech or authenticate Sarvam. `uv run python scripts/diagnose_database.py` checks DNS/TCP without transmitting the database password.

## Configuration

`.env.example` lists the required credentials and listener settings:

- `CEREBRAS_API_KEY`, `SARVAM_API_KEY`.
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
- `DATABASE_URL`: Supabase Session pooler URL, with reserved password characters percent-encoded.
- `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`.
- `APP_ORIGIN`: frontend origin; use the deployed HTTPS URL in production.
- `API_HOST`, `PORT`: HTTP listener, default `0.0.0.0:8080`.

MCP connectors are development tools and are not required inside the application image.

## Architecture and data

The deterministic commerce engine owns prices, stock, totals and budgets. Web and voice use the same engine. Order confirmation requires an unchanged reviewed snapshot, completed review delivery and a later explicit user approval. Session state is persisted and reloaded across reconnects.

The catalog contains historical Flipkart listings and demo inventory. Search uses PostgreSQL full-text matching, intent normalization and validated metadata filters. The evaluated hybrid candidate was rejected; see [evaluation findings](docs/discovery-evaluation.md). No pgvector migration was applied.

Catalog preparation/import tools remain under `scripts/`; migrations remain under `supabase/migrations/`. Imports and migrations are explicit operations, never application startup tasks. See [catalog import](docs/catalog-import.md) before running them.

This is a deployable demo, with no real payments, fulfillment or shipments. Profile addresses currently use Supabase user metadata; its limits are documented in the [HTTP API](docs/http-api.md).

- [Architecture](docs/ARCHITECTURE.md)
- [Commerce engine](docs/commerce-engine.md)
- [HTTP API](docs/http-api.md)
- [Voice pipeline](docs/voice.md)
- [Frontend](web/README.md)
