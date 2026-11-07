# Tests

Install development dependencies with `uv sync --locked`.

```sh
uv run pytest
uv run ruff check .
bash scripts/test_database.sh
```

The database script starts disposable local PostgreSQL, applies migrations and removes the container afterward. Do not point tests at shared or production databases. Without `TEST_DATABASE_URL`, database tests are skipped.

For the isolated browser flow, run Chrome with CDP on localhost:9223, then `RUN_BROWSER_TESTS=1 bash scripts/test_database.sh`. This covers authentication, catalog filters, cart changes, order confirmation, history, profiles and responsive layout.

Optional real-provider checks in `docs/voice.md` require explicit environment flags and are excluded from ordinary test runs. They use local shopping fixtures and must never run against production accounts.
