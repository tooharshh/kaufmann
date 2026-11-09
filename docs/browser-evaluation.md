# Browser evaluation implementation status

The local implementation adds delivery proposals with spoken-delivery receipts and later approval, persisted discovery arguments/rejections/selection, isolated catalog versions, server-authorized catalog selection, and bounded user-owned shopping preference storage. Profile provides correction/forget controls and a catalog selector. The voice worker runs preference extraction through a bounded background queue using the existing Cerebras model. No provider or dependency was changed by this implementation.

## Operator catalogs

Use `uv run python scripts/catalog.py validate SOURCE --mapping MAPPING --report-dir REPORT_DIRECTORY` before importing. CSV and JSON arrays are supported. `fields` maps normalized names to source column names; required fields are `id`, `name`, `price`. Declare `price_unit` as `rupees` or `paise`. Either map `currency` or explicitly configure `currency: INR`. Only INR is supported.

Optional mappings: `category` (a string path separated by ` >> `), `description`, `brand`, `name_te`, `attributes` (JSON object with string/string-array values), `images` (JSON array), `variants` (JSON array), `stock` (integer). Missing stock stays unknown unless `demo_inventory` explicitly supplies an integer policy. Stock responses identify source/demo/unknown basis.

Validation writes accepted, rejected and summary JSON reports. Any rejected row prevents import. Use `import` with the same arguments plus `--name NAME` to create a ready immutable product version. Activate for a verified evaluator account with `activate CATALOG_UUID --user USER_UUID`. Activation grants that user access and selects the version. These operator commands use DATABASE_URL and must only target a reviewed environment. They are not public upload endpoints.

The authenticated `/api/catalog-selection` endpoint lists authorized catalogs (GET) or selects an already authorized catalog (POST with catalog_id). It cannot grant access. Voice dispatch binds catalog ID and selection generation; a switch invalidates reviews and ends the old voice session. Shopping carts are scoped by user and catalog; order history retains old snapshots. The legacy default catalog remains writable by its existing operator seed command for compatibility; ready imported product versions reject mutation.

## Memory and delivery

`/api/memory` GET returns the caller's bounded facts and revision. POST accepts operation remember/forget, fact {subject,scope,key,value}, and optional revision for optimistic concurrency. Keys are size, language, brand, material and response_style. Address/contact details do not belong in this store. Scope and recipient identity remain separate. Automatic extraction stores source turn IDs and explicit source-backed facts, not transcripts. A memory epoch prevents an old queued extraction from undoing a correction or forget.

Voice address proposals patch only volunteered fields. Completed speech and a later actual approval are required before commit. Cart changes invalidate proposals and committed address changes invalidate order review. Address-book saving remains a separate explicitly requested action through the existing scoped profile service and revision checks.

## Verification and remaining release work

The full database and browser regression passes 66 tests, with six optional provider tests skipped. The browser check now covers memory correction/forgetting, rejected-product filtering, catalog switching and dynamic facets in addition to checkout and history. Ruff and whitespace checks pass. The frontend build uses the existing locked dependencies. Two differently mapped smoke catalogs validate successfully.

The authored suite now contains 80 multilingual intent cases and twenty browser-audio workflow definitions. The complete real-model intent baseline is recorded in `docs/evidence/browser-intents-20261108.json`: 47 of 80 cases passed, twenty failed tool/argument expectations, and thirteen encountered provider errors. Accuracy among completed requests is 70.1%; accuracy across all attempts is 58.8%. No forbidden action calls were observed in this simulated-output protocol. These are tool-intent checks, not end-to-end safety or shopping-quality proof. Telugu labels still require bilingual review.

The baseline exposed an unsupported `add` operation for preference memory. The tool now enumerates only remember/forget and supported keys. A separate four-case follow-up passes English, Telugu script and mixed input; Romanized Telugu remains unsuccessful. The follow-up is kept separate from the baseline.

Remaining priorities are Telugu numeric interpretation (one eight-hundred-rupee budget was interpreted as 80000000 paise), exclusions expressed as invented filter fields, unnecessary clarifications despite supplied budgets, and Romanized Telugu memory requests. The baseline is development evidence and must not be represented as a held-out benchmark after using it for fixes.

Actual browser-audio recordings, bilingual human review, end-to-end relevance/constraint/task/memory judgments, and first-audio/playback latency remain outstanding. `scripts/evaluate_audio.py` reports all twenty workflows as missing evidence until real recordings and reviewed traces are supplied. See `docs/evaluation.md` for reproducible commands and trace format. The small catalog files are smoke fixtures, not evidence of unseen-catalog recommendation quality. No shared Supabase migration or deployment has been performed.

Apply migrations only after review. Rollback application and schema changes together: the new engine requires the new columns and the legacy single-user session uniqueness is replaced. This is not a rolling-compatible migration for the old build; deployment needs a coordinated traffic pause or a separately prepared compatibility migration. Keep old catalog versions and order snapshots; do not delete them during rollback.

## November 9 memory and language follow-up

Shared lexical/numeric aids now preserve the original request while assisting interpretation of common Telugu/Romanized vocabulary. Explicit single-budget conversions are checked before a mutation, preventing the observed 800-rupee to 80000000-paise error. Memory retention now has canonical size/recipient labels, source validation, targeted inspection and a scope_required response instead of false success for wrong-scope deletion.

The focused language run passed 18/20 cases without provider errors. The two recipient-label failures were addressed and a separate four-language recheck passed 4/4. Real-provider selective extraction matched 20/20 cases, including rejecting temporary budgets and one-off purchases. Keep these focused results separate from the earlier 80-case baseline; no new full 80-case score is claimed. The full regression now passes 90 tests with six optional tests skipped. Evidence is recorded in `docs/evidence/language-intents-20261109.json`, `docs/evidence/recipient-memory-20261109.json` and `docs/evidence/selective-memory-20261109.json`. Live audio and bilingual review remain outstanding.
