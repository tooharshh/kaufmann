# Next implementation proposal

This proposal needs approval under AGENTS.md before changing cart/confirmation behavior or adding tables. The existing 13-column products table remains unchanged. No new Python dependencies are proposed.

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
