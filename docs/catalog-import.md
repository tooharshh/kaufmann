# Catalog import

The Supabase `public.products` table now uses the 13 source column names requested by the user. The applied migrations live in `supabase/migrations/`; the latest is `20261106135909_use_flipkart_columns.sql`.

## Browser import

The user uploaded `data/processed/flipkart/browser-import.csv` through Supabase Table Editor. Verified 20,000 unique records, including 78 with missing or nonpositive discounted prices. The upload file removes only `description` and `brand`; the raw CSV is unchanged.

Regenerate the upload file with:

```sh
uv run python scripts/prepare_catalog.py --browser-csv data/processed/flipkart/browser-import.csv
```

`uniq_id` is the primary key. `crawl_timestamp` is a timestamp with timezone; prices are nullable decimal rupee amounts; `is_FK_Advantage_product` is a boolean with its exact case preserved. All remaining fields are text, including source list-like strings, specifications, and ratings such as `No rating available`. Missing prices are accepted for source import and must be excluded from future purchasable-product results. Stock and Telugu names are not invented.

## Application preparation

`uv run python scripts/prepare_catalog.py --output-dir data/processed/flipkart` still prepares the application-facing normalized JSONL and rejects unusable prices. It yields 19,922 accepted records and 78 rejected prices. Normalized prices use integer paise and retain the original source row for compatibility with the source-shaped database table.

The optional `scripts/seed_catalog.py` importer has been adapted to the new names and upserts accepted rows by `uniq_id`. The original Supabase upload was manual. Re-importing updates source fields without deleting unrelated products or resetting demo inventory. Separate commerce tables are documented in `docs/commerce-engine.md`.

## Access and verification

RLS remains enabled. Authenticated shoppers can read the shared catalog; browser API roles cannot mutate it, and anonymous users have no access. Dashboard imports use privileged project access rather than shopper permissions.

Both migrations and the complete 20,000-row browser CSV were verified in isolated local Postgres. Integration tests cover upserts, atomic rollback, authenticated reads, and denied browser writes. Supabase security advisors report no findings.

## Catalog search

`src/catalog/search.py` provides async `Catalog.search` and `Catalog.get` operations through a connection pool. Search uses parameterized English full-text matching, a category substring filter, an optional maximum price in paise, and at most ten results. Ordering is deterministic by relevance, price, then product ID. This is lexical search; semantic retrieval and Telugu query translation are not implemented yet.

Search excludes unpriced and known out-of-stock listings. Direct lookup retains them with explicit price/stock status. Results expose integer paise, historical price provenance, demo inventory quantities where configured, and null Telugu names. Missing facts remain unknown. Expected outcomes use explicit statuses: `ok`, `not_found`, `invalid_input`, or `unavailable`.

Try `uv run python scripts/search_catalog.py shoes --category Footwear --max-price 1000`, or use `--id` for an exact lookup. Direct Postgres connectivity is required. Search/filter behavior and unavailable-backend responses are tested locally; the same parameterized search was verified against the uploaded Supabase catalog through MCP.

Direct database connectivity is now verified. Application search and comparison both succeeded against the live catalog without modifying records.

## Product comparison

`Catalog.compare` loads two to four IDs in one query, preserves requested order, and rejects incomplete ID sets rather than silently comparing fewer products. It returns historical prices, exact integer price differences, lowest-priced IDs when every price is known, and attribute values aligned by product ID. `attributes` selects up to ten named fields; the default includes up to twelve source attributes, prioritizing those present across more products.

The specification parser handles the source's hash-arrow notation without evaluating code or changing arrows inside quoted values. Unlabeled or malformed entries remain unknown. Repeated attribute values are retained. Missing prices suppress lowest-price claims; missing attributes remain null. Specification text is historical source content, not application instructions or current store commitments.
