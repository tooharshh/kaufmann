import argparse
import asyncio
import json
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.ingest import prepare_catalog
from src.catalog.repository import import_products
from src.config import Settings


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/flipkart/flipkart_com-ecommerce_sample.csv"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    products, _, report = prepare_catalog(args.input)
    result = {key: report[key] for key in ("accepted", "rejected", "source_sha256")}
    if args.dry_run:
        print(json.dumps({"status": "dry_run", **result}))
        return 0
    try:
        settings = Settings.load()
        async with (
            asyncio.timeout(90),
            await psycopg.AsyncConnection.connect(
                settings["DATABASE_URL"],
                connect_timeout=10,
                sslmode="require",
                prepare_threshold=None,
            ) as connection,
        ):
            count = await import_products(connection, products)
    except (psycopg.Error, TimeoutError, ValueError) as exc:
        print(json.dumps({"status": "database_error", "type": type(exc).__name__}))
        return 1
    print(json.dumps({"status": "ok", "upserted": count, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
