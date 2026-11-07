# Commerce engine

Approved and implemented in `src/engine/` and `src/state/`. The migration is `supabase/migrations/20261106150627_commerce_engine.sql`. The existing 13-column products table is unchanged. No additional Python dependencies were required.

## Persistence

- `shopping_sessions`: UUID primary key, unique authenticated user ID, integer cart version, optional budget in paise, current delivery address, standing instructions, language, saved result IDs, pending review snapshot/token hash/version, and creation/update timestamps. One active shopping session per account supports web/voice reconnects and handoffs.
- `cart_items`: session/product composite primary key, product foreign key, positive integer quantity.
- `demo_inventory`: product primary/foreign key, nonnegative available quantity, explicit demo marker. Initialize ten units for each positively priced listing; unpriced listings cannot be added. Availability is simulated store state, never a claim about Flipkart stock.
- `orders`: UUID primary key, authenticated owner, unique confirmation operation identity, immutable address/total snapshot, explicit demo status, creation timestamp.
- `order_items`: order/product key, immutable product name, quantity, unit price and line total in paise.

Enable RLS and owner-scoped read policies on session, cart, and order data. Catalog/inventory reads require sign-in. Browser roles have no direct mutation permissions. Backend operations derive identity from verified authentication, never model arguments.

## Engine behavior

Implement explicit add, set quantity, remove, budget, address, prepare, and confirm operations. Return structured statuses and authoritative state. All price arithmetic uses integer paise from database values. Reject invalid changes without modifying the cart.

Lock the session row for each mutation and require the caller's expected version. A real cart change increments the version and clears pending review/approval. Address changes also invalidate checkout review. Unchanged values are no-ops. Persist standing instructions and result references through the same versioned session path; never overwrite a newer web edit with an older voice snapshot.

Budget exceptions authorize only the specific proposed edit at its quoted total and current version, without permanently changing the budget. A changed proposal requires fresh agreement.

`prepare_order` requires a nonempty cart, valid prices, sufficient demo stock, and an address. It returns a read-back snapshot and pending token. Voice confirmation additionally requires a completed read-back delivery receipt and a later real user message. Interrupted speech does not authorize confirmation. The engine accepts only trusted application provenance for those events, not model-supplied booleans.

`confirm_order` locks the session and relevant inventory rows, validates the token/version/current price/stock/address, creates immutable order snapshots, and decrements demo inventory in one transaction. Repeated confirmation returns the existing order. Changed prices require a new review. Publish success only after commit.

## Verification

Cover a successful complete checkout, quantity correction, rejected changes, a scoped budget exception, simultaneous web/voice edits, interrupted review, stale tokens, price/stock changes, and duplicate confirmation. Verify reconnect persistence and cross-user isolation in isolated Postgres before applying approved migrations remotely. No payment or fulfillment integrations are included.

## Runtime contract

Construct `CommerceEngine(pool, authenticated_user_id)` only from a verified server-side identity. User IDs, message IDs, and delivery receipts are not LLM tool arguments. The HTTP API now verifies Supabase tokens for catalog/cart/session operations and order reads. The browser adapter acknowledges rendered reviews and registers later confirmation clicks. The voice adapter binds actual SDK user messages and completed uninterrupted speech to the same gate.

Runtime code calls `record_user_message(message_id)` when an actual user event is committed. Repeated message IDs do not advance the event sequence. It calls `record_review_delivery(token, delivery_id)` only after speech completes or the read-back is rendered successfully, and `interrupt_review(token)` on interruption/cancellation. A new user message arriving before delivery also invalidates the review. Never expose those methods as model tools or treat queued output as delivered output.

Cart APIs are `add_item`, `set_quantity`, `remove_item`, `set_budget`, `set_address`, `approve_budget_exception`, `prepare_order`, and `confirm_order`. Every mutation takes the expected persisted version. Approval methods receive the actual current message ID injected by the runtime. `set_quantity(..., 0, ...)` removes the item; `add_item` adds to the existing quantity. Address updates merge explicitly supplied fields, preserving omitted fields. Checkout requires recipient, line1, city, state, a six-digit Indian postal code, and country IN; this validates structure, not deliverability.

`update_context` adds/removes specific standing instructions, sets language, or saves ordered result IDs. `resolve_reference` resolves a one-based position against that persisted ordering. Context changes conservatively invalidate reviews and budget exceptions; unchanged values do not.

Budget exceptions require a later registered user message and match the exact proposed snapshot/version. Reducing an already approved over-budget cart is allowed while preserving the original budget; further increases need new agreement. Lowering a budget below the existing total is allowed, but checkout then requires a scoped exception. Orders retain immutable snapshots through the engine API. HTTP cart actions now call the engine; browser checkout uses its rendering adapter; model tools and speech delivery hooks now use the same engine.

Expected failures return structured statuses such as `conflict`, `out_of_stock`, `inventory_unknown`, `unpriced`, `over_budget`, `stale_token`, `review_not_delivered`, or `later_user_approval_required`. Database failures roll back and return `unavailable`; success is returned only after commit. Token values are generated securely and only hashes are persisted.

Run `bash scripts/test_database.sh` for the full suite on disposable local Postgres. The helper creates local auth-role stubs, applies migrations, runs tests, and removes the container. It never loads production credentials. Tests verify commerce semantics and simulate trusted delivery events; full browser LiveKit speech delivery and real Supabase sign-in are not exercised by these tests.

Run `bash scripts/test_database.sh` for disposable-database regression checks; optional browser and live-provider checks are described in `docs/voice.md`. Historical catalog inventory is demo data. No migrations or shopper data are created on startup.
