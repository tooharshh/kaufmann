# Store frontend

The API serves the built storefront from `web/dist`. Build it with `npm ci && npm run build` from this directory, then start the API with `uv run python -m src.api`. `docker compose up --build` builds and serves the storefront and API together. Astryx, React and Vite versions are pinned in `package.json` and `package-lock.json`.

```sh
uv sync --locked
uv run python -m src.api
```

Open http://localhost:8080. Create an account and confirm your email if Supabase requires it, then sign in. The storefront supports catalog search and continuous scrolling, product details, comparison, saved baskets, budgets and scoped exceptions, delivery details, preferences, and explicit demo checkout.

Authentication currently uses email and password. Google sign-in is temporarily unavailable while the linked mail-account issue is resolved.

The page obtains only the Supabase project URL and public publishable key from `/api/config`. Access and refresh tokens stay in sessionStorage; logging out clears local shopper drafts. All catalog and commerce calls require authenticated access. Prices and availability come from the backend.

Checkout displays the engine read-back before enabling confirmation. Canceling discards that review; confirmation is a separate user click. Orders use historical catalog prices and demo inventory. There are no payments or shipments. Start `uv run python src/agent.py dev` in another terminal, then select **Talk to Kaufmann** and allow microphone access. See `docs/voice.md` for details.

The Docker image includes this frontend. See `docs/http-api.md` for server configuration. Same-origin hosting works automatically; `APP_ORIGIN` permits a separate frontend origin.

Run `bash scripts/test_database.sh` for backend checks. With Chrome exposing CDP on localhost:9223, `RUN_BROWSER_TESTS=1 bash scripts/test_database.sh` also exercises sign-in, comparison, cart edits, budget approval, canceled and confirmed checkout, reconnect persistence, and mobile layout against isolated local services. No production accounts or orders are created.

Product photos use the source catalog's image URLs. Historical `img5a.flixcart.com` and `img6a.flixcart.com` links are normalized to HTTPS on `rukminim2.flixcart.com`; the old hosts returned 403 during verification. The browser retries alternate catalog images if one fails. Some historical files may no longer exist, in which case the existing placeholder remains. No product image is fabricated or replaced with an unrelated stock photo.

The storefront uses a warm editorial retail layout with Astryx product components, a responsive catalog, product galleries, comparison, profile and saved-cart pages. The signed-out landing fits a single screen; after sign-in, the marketplace focuses on live catalog results. Open **Cart** for a dedicated saved-cart page with line items, quantities, removal, budget, delivery details, preferences and checkout. The floating Kaufmann orb starts or ends LiveKit voice. It shows the current transcription or response and catalog-backed product cards without keeping transcript history. English/Telugu language preference and recommendation quick-add use the existing LiveKit and commerce APIs.

The catalog is one continuous page, fetching sixty listings at a time as you scroll. There are no page numbers or next/previous controls. A load-more button is available as a keyboard-accessible alternative. Browsing batches do not overwrite the agent's saved result references.

`/cart` and `/product/PRODUCT_ID` support reloads and browser history. Navigation within the signed-in store preserves the active voice connection. Adding a product opens `/cart` only after a successful engine result; budget refusals stay pending until explicitly approved. Carts remain persisted per authenticated account.

Clicking a product opens its page and saves its identifier through the existing context operation. While voice is connected, a private selection event makes Kaufmann ask whether more details are wanted. **Ask Kaufmann** starts voice when disconnected. Agent product-detail/reference tools move the screen to the relevant product, and successful voice additions move it to the cart. Only events from an agent participant in the current authenticated room are accepted; payloads select fixed application views rather than arbitrary URLs. Reconnect voice after updating from an older client token.

The catalog's Sort & filters panel includes observed source values for color, size, gender, brand, material, occasion, fit, pattern, sleeve and type, plus category, price bounds, minimum rating and demo inventory status. Sorting supports relevance, both price directions, rating and historical catalog date. Voice search applies these same controls. Unknown attributes are excluded from active attribute filters; listed sizes do not establish size-specific inventory.

Catalog controls use an expanded, independently scrolling left sidebar on desktop. At widths up to 900px the same controls move into an accessible modal drawer, opened with Filters & sort. Browser and agent selections remain shared across both layouts.

Profile at `/profile` provides account tiles, editable name/contact details, a saved-address book and an orders link. Address edits preserve other fields. Use for checkout applies a saved address through the commerce engine; saved order snapshots never change. Sign-in email is read-only; contact details do not change authentication credentials.
