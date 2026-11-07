# Catalog data

The raw Flipkart source lives in `flipkart/`. Run `uv run python scripts/prepare_catalog.py --output-dir data/processed/flipkart` to prepare listings and a rejection report locally. Generated data is ignored by git. See `docs/catalog-import.md` for normalization rules and the proposed Supabase import. Stock and Telugu translations are not generated.
