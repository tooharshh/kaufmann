# HTTP API

Start locally with `uv run python -m src.api`. The Docker image starts the same API by default. Set `PORT` for the HTTP listener (default 8080), `API_HOST` for its bind address (default 0.0.0.0), and `APP_ORIGIN` for the exact allowed browser origin (default http://localhost:5173). Use `/health` as the Render health-check path. The voice worker will run as a separate process using the same image after implementation.

## Authentication

Clients sign up/sign in through Supabase Auth using the project URL and publishable key. The bundled storefront implements email/password sign-up, sign-in, and token refresh. Send the resulting access token as `Authorization: Bearer TOKEN` on authenticated `/api/` requests. The backend validates each token with Supabase's `/auth/v1/user` endpoint, derives the account UUID from its response, and rejects anonymous identities. Auth failures and outages fail closed. No client-supplied user ID or decoded-but-unverified JWT claims are used.

Authorization headers and request bodies are not logged. Responses use `Cache-Control: no-store`. CORS allows the server origin and configured `APP_ORIGIN`; preflight requests do not require authentication. Cookies are not used for backend authentication. No API route accepts a Supabase service key, database URL, message sequence, approval message ID, or client-generated delivery receipt.

## Routes

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/`, `/cart`, `/product/{id}` | Public application shells; data requires sign-in |
| GET | `/api/config` | Public Supabase URL and publishable key only |
| GET | `/health` | Public process liveness |
| GET | `/ready` | Public bounded Postgres readiness |
| GET | `/api/catalog/search` | English lexical search; query, category, max_price_paise, limit (up to 100), offset; returns has_more |
| GET | `/api/catalog/{product_id}` | Exact listing lookup |
| POST | `/api/catalog/compare` | JSON product_ids and optional attributes |
| POST | `/api/voice/session` | Empty JSON; authenticated private room grant with agent dispatch |
| GET | `/api/session` | Current authenticated shopper's persisted state |
| POST | `/api/actions/{action}` | Versioned cart/session operation |
| GET | `/api/orders/{order_id}` | Immutable order snapshot, filtered by authenticated owner |

All catalog, state, action, and order routes require sign-in. Request bodies are JSON objects, limited to 16 KiB; unknown fields are rejected. Money in API requests and responses uses integer paise. Results retain the engine's explicit status; invalid inputs use HTTP 400, missing resources 404, conflicts/business refusals 409, and unavailable services 503.

## Actions

Every action requires `expected_version` from the latest state. User actions register a server-generated user-event UUID before calling the existing engine. Saving result IDs alone and resolving references are system context operations and do not manufacture user events. These endpoints represent authenticated web user actions; voice tools must call the engine directly with their actual committed turn provenance, not use HTTP requests to manufacture extra user turns.

| Action | Additional required fields | Optional fields |
| --- | --- | --- |
| add_item | product_id, quantity | |
| set_quantity | product_id, quantity | |
| remove_item | product_id | |
| set_budget | budget_paise (null clears it) | |
| set_address | patch | |
| update_context | | add_instruction, remove_instruction, language, result_ids |
| resolve_reference | position | |
| approve_budget_exception | token | |

For example, `POST /api/actions/add_item` accepts `{"product_id":"SOURCE_ID","quantity":1,"expected_version":0}`. A stale version returns `conflict` and the latest state, without replaying the cart edit. A budget exception returns a token for a later explicit approval request, which authorizes only the stored proposal. Successful actions expose a server-generated `X-Request-ID`; it is not accepted as client-controlled provenance.

## Browser checkout

`POST /api/checkout/prepare` accepts `expected_version` and returns the engine read-back and pending token. The storefront renders the review dialog and waits for two animation frames while visible before calling `/api/checkout/rendered` with `token`. The server generates the delivery receipt; clients cannot submit receipt IDs or delivery booleans. This is the web rendering adapter, not a voice speech-delivery acknowledgment.

A separate explicit confirmation click sends `token` and `expected_version` to `/api/checkout/confirm`. The server registers that later user event and invokes the unchanged engine gate. `/api/checkout/cancel` accepts `token` and invalidates the pending review. Stale versions, changed carts, missing delivery, and premature confirmations remain rejected. An uncertain confirmation response can be retried with the same token to retrieve the committed order.

## Verification

`bash scripts/test_database.sh` tests real HTTP requests against local auth responses and disposable Postgres. Coverage includes rejected credentials/anonymous access, authentication outages, CORS, malformed bodies, identity spoofing, cart version conflicts, budget exceptions, and owner-scoped order reads. Browser coverage uses isolated auth responses and real local engine/database operations; Supabase email delivery and production sign-in were not exercised.

Run `bash scripts/test_database.sh` for disposable-database regression checks; optional browser and live-provider checks are described in `docs/voice.md`. Historical catalog inventory is demo data. No migrations or shopper data are created on startup.

The storefront consumes catalog batches as one continuous list, rather than exposing page controls. The room grant now allows a private application data channel as well as microphone media. The worker disables generic text input and handles only validated selection events from the bound shopper. No selection/navigation endpoint can place or confirm an order.

## Order history

`/orders` serves the authenticated storefront view. `GET /api/orders?offset=0` requires a verified user token and returns only that user's immutable saved order snapshots, newest first, in batches of 50 with `has_more`. The browser appends older orders on the same page.

Catalog search accepts inclusive `min_price_paise`/`max_price_paise` bounds and `sort_by=relevance|price_asc`. Reversed bounds and invalid sorts return invalid_input. Voice navigation carries the same filters to the browser.

## Catalog facets

`GET /api/catalog/filters` requires authentication and returns observed categories, up to 60 common values per attribute, and sort names. Search accepts JSON `filters` with keys color, size, gender, brand, material, occasion, fit, pattern, sleeve and type. Attribute filters combine with AND; brand matches a complete listed brand; colors/materials match bounded words, and M/S/L include their named size aliases. Unknown attributes do not match. Values are escaped and SQL parameters are bound. `min_rating` accepts zero through five, excluding unrecognized ratings. `availability` is discoverable (default: positive or unknown demo stock), available, out_of_stock, unknown or all. Sorts include relevance, price_asc, price_desc, rating_desc (unknown last), newest (historical crawl time). No schema changes were made.

## Profile

`/profile` serves the account page. Authenticated `GET /api/profile` reads the current user's name, contact phone/email, login email and saved addresses from their Supabase user record. `POST /api/profile` accepts operation (details, save_address, delete_address, default_address), data and revision. Saved address updates are patches; unknown IDs fail rather than creating a new address. Login credentials and authorization metadata are never modified. Contact phone is unverified; contact email does not change sign-in email. Data is stored under kaufmann_profile user metadata and never used for authorization. The demo bounds it to five addresses and 4000 UTF-8 bytes to limit JWT metadata size. Revision checks and per-user in-process serialization reject ordinary stale writes; metadata does not supply a cross-instance transactional compare-and-swap guarantee.

Saving or deleting a profile address does not mutate a cart or past order. Use for checkout calls the existing versioned set_address engine action, preserving confirmation invalidation. Current checkout address is displayed separately and can be saved into the address book. A default marker is an address-book preference, not an automatic checkout mutation.
