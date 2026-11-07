# Production build

The application uses separate containers for the HTTP storefront/API and LiveKit voice worker. Providers remain Cerebras GPT-OSS 120B and Sarvam. The frontend has no Node build step.

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

Use `Dockerfile.api` for the web service with its default `python -m src.api` command. Set the web health path to `/health`; the API honors Render's `PORT` environment variable. Set environment variables through the Render dashboard/secret store, never through image build arguments. Use the values in `.env.example`; `APP_ORIGIN` can use Render's external URL automatically.

This prepares deployment artifacts; it does not provision or deploy Render services. Apply any approved migrations separately. Existing migrations and the imported catalog are preserved.

## Validation and limits

Before release, sign in and verify discovery, product focus, cart edits, single-field address corrections, order history/profile, interruptions and explicit checkout confirmation. Real microphone-to-speaker quality and provider quotas need operational checks after deployment.

This remains a demo commerce application: inventory and orders are persisted, but no real payments, fulfillment or shipment tracking are integrated. The saved-address book currently uses Supabase user metadata. See `docs/http-api.md` for its size and concurrency limits.

Numeric voice metrics remain enabled on the server without transcript logging. Browser audio timing diagnostics are opt-in: open `/?voice_debug=1`, connect voice, then inspect `window.kaufmannVoiceMetrics()` in browser developer tools. Normal storefront sessions do not create the diagnostic audio analyser.

## Free hosted demo: Render + LiveKit Cloud

Create a Render Blueprint from this repository using `render.yaml`. It creates only a free web service in Singapore; automatic deployments are off. Set the prompted secrets in Render: `CEREBRAS_API_KEY`, `SARVAM_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `VOICE_DISPATCH_SECRET`, `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_PUBLISHABLE_KEY`. With `APP_ORIGIN` unset, the app uses Render's external URL. Keep Supabase unchanged and configure its authentication site/redirect URLs for the resulting HTTPS domain.

Deploy the worker on LiveKit Cloud Build with the root `Dockerfile`; Render uses `Dockerfile.api`. Authenticate the official LiveKit CLI and select the existing project. Keep the generated `livekit.toml` project/agent IDs for subsequent deployments. Add `CEREBRAS_API_KEY`, `SARVAM_API_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `VOICE_DISPATCH_SECRET` in LiveKit's encrypted secret settings. LiveKit injects its own `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`; do not override those.

Both hosts now require an independent `VOICE_DISPATCH_SECRET`. Generate a cryptographically random value, at least 32 bytes, and set the exact same value on Render and LiveKit. Never reuse the auto-generated LiveKit API secret for dispatch signing. Existing local installations also need this variable supplied manually; `.env` is never automatically edited. Changing it invalidates pending room dispatches, so reconnect voice after rollout.

Render's free API sleeps after inactivity. LiveKit Build includes 1,000 agent session minutes per month and can cold-start in 10–20 seconds. The browser allows 90 seconds for an agent to join. Free allowances are capped; speech/provider credits remain separate. No keep-alive pings or paid upgrades are configured.

Before live validation, stop the local worker to avoid competing dispatches. Check HTTPS, health/readiness, login, products, microphone, screen navigation and persisted cart/address changes. Keep order-confirmation tests on disposable fixtures. Roll back free deployments by redeploying the previous known-good revision.
