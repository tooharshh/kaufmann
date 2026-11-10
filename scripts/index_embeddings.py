"""Explicit, resumable operator indexing; never runs during app startup."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import aiohttp
from dotenv import load_dotenv
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.embeddings import (
    PROFILE,
    EmbeddingUnavailable,
    GeminiEmbeddings,
    document_hash,
    document_text,
)
from src.db.connection import create_pool


async def run(args):
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY") or not os.environ.get("DATABASE_URL"):
        raise SystemExit("Configure GEMINI_API_KEY and DATABASE_URL in the environment")
    pool = create_pool(os.environ["DATABASE_URL"])
    await pool.open()
    report = {"status": "ok", "indexed": 0, "unchanged": 0, "concurrent_changes": 0}
    try:
        async with pool.connection() as connection:
            connection.row_factory = dict_row
            cursor = await connection.execute(
                "select p.*, e.content_hash as indexed_hash from public.products p "
                "left join public.product_embeddings e on e.product_id=p.uniq_id "
                "and e.catalog_id=p.catalog_id and e.profile=%s "
                "where p.catalog_id=%s order by p.uniq_id",
                (PROFILE, args.catalog),
            )
            rows = await cursor.fetchall()
        if not rows:
            raise SystemExit("Catalog has no products")
        async with aiohttp.ClientSession() as http:
            client = GeminiEmbeddings(http, os.environ["GEMINI_API_KEY"])
            attempts = 0
            for row in rows:
                digest = document_hash(row)
                if digest == row["indexed_hash"]:
                    report["unchanged"] += 1
                    continue
                if attempts >= args.limit:
                    report["status"] = "partial"
                    break
                if attempts:
                    await asyncio.sleep(args.delay)
                attempts += 1
                try:
                    vector = await client.embed(document_text(row))
                except EmbeddingUnavailable as exc:
                    report.update(status="partial", error=str(exc))
                    break  # Preserve progress; do not hammer quota/auth failures.
                async with pool.connection() as connection, connection.transaction():
                    connection.row_factory = dict_row
                    cursor = await connection.execute(
                        "select * from public.products where uniq_id=%s and catalog_id=%s for update",
                        (row["uniq_id"], args.catalog),
                    )
                    current = await cursor.fetchone()
                    if not current or document_hash(current) != digest:
                        report["concurrent_changes"] += 1
                        continue
                    await connection.execute(
                        "insert into public.product_embeddings(product_id,catalog_id,profile,content_hash,embedding) "
                        "values(%s,%s,%s,%s,%s::extensions.vector) "
                        "on conflict(catalog_id,product_id,profile) do update set "
                        "content_hash=excluded.content_hash,embedding=excluded.embedding,updated_at=now()",
                        (row["uniq_id"], args.catalog, PROFILE, digest, vector),
                    )
                report["indexed"] += 1
        if report["concurrent_changes"]:
            report["status"] = "partial"
        print(json.dumps(report))
        return 0 if report["status"] == "ok" else 2
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=UUID, required=True)
    parser.add_argument(
        "--limit", type=int, default=100, help="Maximum paid/API requests in this run"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=6,
        help="Seconds between requests; tune to project quota",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 50000 or not 0 <= args.delay <= 60:
        parser.error("limit must be 1..50000; delay must be 0..60")
    raise SystemExit(asyncio.run(run(args)))
