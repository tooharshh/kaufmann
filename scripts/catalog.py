"""Validate, import and activate isolated operator catalogs."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from dotenv import load_dotenv

from src.catalog.selection import select_catalog
from src.catalog.versioned_import import import_version, validate_catalog
from src.db.connection import create_pool


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "import"):
        sub = commands.add_parser(command)
        sub.add_argument("source", type=Path)
        sub.add_argument("--mapping", required=True, type=Path)
        sub.add_argument("--report-dir", required=True, type=Path)
        if command == "import":
            sub.add_argument("--name", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("catalog_id", type=UUID)
    activate.add_argument("--user", required=True, type=UUID)
    args = parser.parse_args()
    if args.command != "activate":
        products, rejected, report = validate_catalog(
            args.source, json.loads(args.mapping.read_text())
        )
        args.report_dir.mkdir(parents=True, exist_ok=True)
        for name, value in (
            ("accepted", products),
            ("rejected", rejected),
            ("report", report),
        ):
            (args.report_dir / (name + ".json")).write_text(
                json.dumps(value, ensure_ascii=False, indent=2)
            )
        print(json.dumps(report))
        if rejected:
            raise SystemExit(1)
        if args.command == "validate":
            return
    import os

    load_dotenv()
    database_url = os.environ["DATABASE_URL"]
    if args.command == "import":
        async with await psycopg.AsyncConnection.connect(database_url) as connection:
            catalog_id = await import_version(
                connection, args.name, products, rejected, report
            )
        print(json.dumps({"catalog_id": str(catalog_id), "activated": False}))
    else:
        async with create_pool(database_url) as pool:
            async with pool.connection() as connection:
                await connection.execute(
                    "insert into public.catalog_grants(user_id, catalog_id) values (%s,%s) on conflict do nothing",
                    (args.user, args.catalog_id),
                )
            print(json.dumps(await select_catalog(pool, args.user, args.catalog_id)))


if __name__ == "__main__":
    asyncio.run(main())
