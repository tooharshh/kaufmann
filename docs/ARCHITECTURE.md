# Architecture outline

The catalog, deterministic commerce engine, and authenticated HTTP API are implemented. The API validates user access tokens with Supabase before constructing a user-bound engine. The native HTML/CSS/JavaScript storefront includes authentication, comparison, persisted cart controls, and browser review/confirmation. Cerebras/Sarvam voice agents, signed room dispatch and a speech delivery adapter are implemented; browser audio still needs a human listening check. See `docs/voice.md`. Interfaces are documented in `docs/commerce-engine.md` and `docs/http-api.md`.

## Shared commerce engine

Voice tools and web cart actions use the same deterministic engine. Catalog and engine results supply all prices, stock, totals, and budget decisions. LLM-facing tools return structured results with explicit statuses.

## Order confirmation

The engine's `prepare_order` returns a read-back snapshot and pending token. `confirm_order` requires the unchanged cart version, a trusted review-delivery receipt, and a later registered user message. Cart, address, budget, and context changes invalidate pending review. No-ops preserve it. Orders and inventory updates commit atomically; retries return the existing order.

## Sessions and agents

The engine reloads and locks persisted session state on every operation. It stores instructions, language, ordered product references, address, budget, and confirmation state. State is available across reconnects and future handoffs. Runtime adapters must register actual user messages and delivery/interruption events; the engine does not interpret conversation text or fabricate transport receipts.

## Voice and deployment

The worker uses LiveKit Agents and Sarvam speech, with English/Telugu language mixing and streamed responses. Interruptions stop speech and truncate history to spoken content. Render hosts the application over HTTP; the worker connects outbound to LiveKit Cloud.

## Runtime and deployment

LiveKit Agents, Sarvam, and psycopg are pinned in `pyproject.toml` and `uv.lock`. The API uses the existing locked aiohttp dependency. Supabase stores catalog and commerce state; separate demo inventory starts at ten units per positively priced listing. The Python 3.11 Docker image starts the HTTP API. The buildless frontend is served by the API from the same container. The selected model is Cerebras `gpt-oss-120b`, accessed through the pinned OpenAI-compatible plugin, alongside the pinned Sarvam plugin and bundled LiveKit browser SDK. Concierge, discovery, basket and checkout handoffs share persisted state and only the current request. A non-root multi-stage image and Compose API/worker configuration are provided in `docs/production.md`. Render provisioning and complete browser audio validation remain deployment checks. No payment or fulfillment integrations exist.

## Browser navigation

The API serves the catalog at `/`, product views at `/product/{id}`, and the persisted cart at `/cart`. All product and commerce data still requires verified authentication. The catalog loads bounded batches into one continuous grid; no cart or checkout behavior depends on a catalog batch boundary.

A room-scoped BrowserBridge links authenticated product-selection packets to the runtime and sends catalog/product/cart navigation packets back to that shopper. Selection accepts only an existing product ID and event UUID from the bound shopper identity; arbitrary text and command types are rejected. Browser packets never become chat input or later order approval. Default room text input is disabled. Selected IDs use the existing persisted result-reference field, and fresh catalog facts remain untrusted text data.

A UI selection cancels any voice review before a new details question is generated with no tools. A selection does not add items, register a synthetic approval turn, or place an order. Product tools publish focus, while cart navigation follows a committed successful addition. Browser state changes use history navigation, preserving the microphone connection. Reliable packets remain best effort during disconnection; persisted cart data is reloaded independently. No schema or provider change was required.

The voice dispatch metadata is signed and room-bound. It includes the active user's short-lived Supabase access token so voice profile tools can use the existing user-scoped Auth API. The worker checks the token owner against the signed user ID; profile changes retain the API's revision check and field-patch semantics.
