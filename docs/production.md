# Production build

The application uses one image with two processes: an HTTP storefront/API and a LiveKit voice worker. Providers remain Cerebras GPT-OSS 120B and Sarvam. The frontend has no Node build step.

## Local container release check

Create `.env` from `.env.example` and configure the existing services. Never add it to version control.

```sh
uv sync --locked
uv run ruff check .
bash scripts/test_database.sh
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

Open http://localhost:8080. Compose binds the API to localhost; put an HTTPS reverse proxy in front of it for public access. Microphone access requires HTTPS or localhost. Stop the stack with `docker compose down`.

`PORT` controls the API listener and Compose port mapping. `APP_ORIGIN` should match the public frontend origin. Voice connects outbound to LiveKit Cloud; no UDP or worker ports are published. The stack uses the existing Supabase database and performs no migrations or seed operations on startup.

The image has a non-root runtime, locked dependencies and no build tools, uv executable, tests, downloaded datasets, model experiments or secrets. Compose drops capabilities and disables privilege escalation. API health is `/health`; `/ready` separately checks database connectivity. Worker health is its internal HTTP `/` endpoint on port 8081. Health status does not prove that every external inference provider is available.

The worker keeps one idle job process and drains active sessions for up to 60 seconds on shutdown. Compose allows 90 seconds before forced termination. Match that grace period in other orchestrators. A session longer than the drain timeout can still be interrupted during deployment.

## Render

Use the Dockerfile for the web service with its default `python -m src.api` command. Set the web health path to `/health`; the API honors Render's `PORT` environment variable. Run the same image as a background worker with `python -m src.agent start`. Set environment variables through the Render dashboard/secret store, never through image build arguments. Use the values in `.env.example`, with `APP_ORIGIN` set to the deployed HTTPS URL.

This prepares deployment artifacts; it does not provision or deploy Render services. Apply any approved migrations separately. Existing migrations and the imported catalog are preserved.

## Validation and limits

Before release, sign in and verify discovery, product focus, cart edits, single-field address corrections, order history/profile, interruptions and explicit checkout confirmation. Real microphone-to-speaker quality and provider quotas need operational checks after deployment.

This remains a demo commerce application: inventory and orders are persisted, but no real payments, fulfillment or shipment tracking are integrated. The saved-address book currently uses Supabase user metadata. See `docs/http-api.md` for its size and concurrency limits.

Numeric voice metrics remain enabled on the server without transcript logging. Browser audio timing diagnostics are opt-in: open `/?voice_debug=1`, connect voice, then inspect `window.kaufmannVoiceMetrics()` in browser developer tools. Normal storefront sessions do not create the diagnostic audio analyser.
