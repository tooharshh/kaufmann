# Optional Gemini semantic search

This feature is isolated from baseline commit `1a51e40` on branch
`feature/gemini-semantic-search`. It is disabled by default and adds no Python
dependency, local inference model, or change to the conversation model.

## Retrieval

The API and voice worker share `Catalog.search`. With `SEMANTIC_SEARCH_ENABLED=true`,
relevance searches use Gemini Embedding 2 and keyword retrieval. The voice tool accepts
an optional `semantic_query` containing descriptive intent, independently of its
English keyword fallback. Browser queries are embedded directly. Google receives
search text, not the full conversation, address book or memory store.

The REST client requests 768 dimensions and normalizes/validates finite nonzero
vectors. It uses the documented `task: search result | query: ...` query prefix and
`title: ... | text: ...` document format. Embedding 2 does not accept `taskType`.
The profile fixes the model, dimensions and document format together.

Each branch first applies the same catalog, budget, stock, category, rating,
attribute and rejected-ID restrictions. Keyword minus exclusions also restrict
the semantic branch. This preserves existing structured constraints; embeddings
do not reliably interpret arbitrary natural-language negations or prove safety
and compatibility. Those must still become validated constraints.

Candidates are ranked with reciprocal rank fusion (equal weights, constant 60).
Each branch supplies at most 1,000 candidates, so hybrid pagination is bounded to
their union. Ties use product IDs. Explicit price/rating/date sorts retain the
existing keyword path and ordering. Blank searches retain normal catalog browsing.

Semantic candidates require cosine similarity of at least 0.55. This is an initial
guard, not a calibrated relevance guarantee. Retrieval currently uses an exact
filtered vector scan in PostgreSQL, with no approximate ANN index. This prioritizes
correct eligibility on this 20,000-product catalog; measure database p95 and query
plans before increasing catalog size or traffic.

Query vectors are cached for five minutes, at most 128 entries, using hashed keys.
Requests time out after three seconds; the search path bounds cache-lock waiting
and embedding work to 3.5 seconds. Failures enter a 30-second cooldown. Provider or
vector-table errors fall back to keyword retrieval. Responses report `retrieval`
and `retrieval_fallback`; fallback is not evidence that semantic retrieval worked.

## Indexing and activation

1. Apply `supabase/migrations/20261110061133_semantic_search.sql` to the reviewed
   database. It requires pgvector in the `extensions` schema, adds a backend-only
   RLS-protected embedding table and a content-change invalidation trigger. Existing
   product/cart/order rows are not rewritten. No public upload endpoint is added.
2. Supply `GEMINI_API_KEY` and `DATABASE_URL` to the operator environment. Do not put
   credentials in Git or command arguments. The CLI runs outside Render; no model
   needs to fit into Render memory.
3. Start with a bounded indexing run:

   ```sh
   uv run python scripts/index_embeddings.py \
     --catalog 00000000-0000-0000-0000-000000000001 --limit 20 --delay 6
   ```

   Increase the limit explicitly after checking the provider's quota and cost.
   The default is 100 calls. Repeated runs skip unchanged content, preserving
   progress across failures. Exit code 2 and `status: partial` mean indexing is
   incomplete. A provider failure stops the run without blind retries.
   Every catalog version needs its own indexing run after import.
4. Finish indexing before enabling; otherwise semantic candidates cover only the
   indexed subset. The CLI reports `ok` only after processing all fetched products.
   Re-run it after changes/imports. Product content changes delete stale embeddings;
   price and stock changes do not require re-embedding. A row lock and content hash
   prevent a concurrent edit from committing a stale embedding.
5. Evaluate real English, Telugu, Romanized and mixed queries, including no-answer
   cases and explicit constraints. Compare keyword and hybrid relevance and latency.
   The tests below prove wiring and invariants, not real-model retrieval quality.
6. Set `GEMINI_API_KEY` and `SEMANTIC_SEARCH_ENABLED=true` on both Render and LiveKit,
   then deploy both from the same commit. Confirm real searches report `hybrid`.

Document embeddings contain product name, category, brand, descriptions, Telugu
name and attributes/specifications, bounded to 10,000 body characters. They exclude
mutable prices/stock and never invent uses or recipient suitability. Content hashes
and invalidation use the same document fields. Ready imported products remain immutable.

## Verification and rollback

`RUN_BROWSER_TESTS=1 bash scripts/test_database.sh` uses the pinned
`pgvector/pgvector:0.8.1-pg17` container and Chrome CDP on port 9223. Provider tests use
a local mock HTTP server; no Google key is required in CI. Database tests verify
semantic matches without keyword overlap, budgets, stock, categories, exclusions,
catalog isolation, indexing resumption, content invalidation and fallback.

A bounded live request on November 10 returned HTTP 402 using the configured key.
No production catalog was embedded, no shared migration was applied, and no feature
flag was enabled. Live model quality and latency remain unverified. Resolve the
provider/account response and repeat a small run before indexing the full catalog.

To disable immediately, set `SEMANTIC_SEARCH_ENABLED=false` on both services and
restart them. For code rollback, revert the dedicated feature commit or deploy
baseline `1a51e40`. The additive embedding table can remain: the old build ignores
it. Do not drop shared extensions or delete catalog/order data during rollback.

References: [Google embedding formats](https://ai.google.dev/gemini-api/docs/embeddings),
[Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector).
