import argparse
import asyncio
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.search import Catalog
from src.config import Settings
from src.db.connection import create_pool


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--max-price")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--id")
    parser.add_argument("--compare", nargs="+", metavar="PRODUCT_ID")
    parser.add_argument("--attributes", nargs="+")
    args = parser.parse_args()
    price = None
    if args.max_price is not None:
        try:
            amount = Decimal(args.max_price) * 100
            if (
                not amount.is_finite()
                or amount <= 0
                or amount != amount.to_integral_value()
            ):
                parser.error(
                    "Price must be a positive rupee amount with at most two decimals"
                )
            price = int(amount)
        except InvalidOperation:
            parser.error("Invalid price")
    settings = Settings.load()
    pool = create_pool(settings["DATABASE_URL"])
    async with pool:
        catalog = Catalog(pool)
        result = (
            await catalog.compare(args.compare, attributes=args.attributes)
            if args.compare
            else (
                await catalog.get(args.id)
                if args.id
                else await catalog.search(
                    args.query,
                    category=args.category,
                    max_price_paise=price,
                    limit=args.limit,
                )
            )
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["status"] not in {"ok", "not_found"})


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
