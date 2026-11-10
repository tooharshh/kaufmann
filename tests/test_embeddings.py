import argparse
import asyncio
import os

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.catalog import embeddings
from src.catalog.embeddings import (
    DIMENSIONS,
    PROFILE,
    EmbeddingUnavailable,
    GeminiEmbeddings,
    document_hash,
    document_text,
    vector_literal,
)
from src.catalog.search import Catalog
from src.catalog.selection import DEFAULT_CATALOG
from tests.test_commerce_engine import shop


def test_vectors_and_document_identity():
    row = {"product_name": "చెప్పులు", "description": "Comfortable footwear"}
    assert document_text(row).startswith("title: చెప్పులు | text:")
    assert document_hash(row) == document_hash(
        {**row, "discounted_price": 200, "available": 0}
    )
    assert document_hash(row) != document_hash({**row, "description": "Changed"})
    for bad in (
        [1],
        [0] * DIMENSIONS,
        [float("nan")] * DIMENSIONS,
        [True] * DIMENSIONS,
    ):
        with pytest.raises(EmbeddingUnavailable):
            vector_literal(bad)


def test_provider_contract_cache_and_failure(monkeypatch):
    async def run():
        requests = []

        async def handle(request):
            body = await request.json()
            requests.append(body)
            assert request.headers["x-goog-api-key"] == "test-only"
            assert body["outputDimensionality"] == DIMENSIONS
            assert "taskType" not in body
            if len(requests) > 1:
                return web.json_response({}, status=429)
            return web.json_response(
                {"embedding": {"values": [1] + [0] * (DIMENSIONS - 1)}}
            )

        app = web.Application()
        app.router.add_post("/embed", handle)
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            monkeypatch.setattr(embeddings, "ENDPOINT", str(server.make_url("/embed")))
            client = GeminiEmbeddings(http, "test-only")
            assert await client.query("నడవడానికి shoes") == await client.query(
                "నడవడానికి shoes"
            )
            assert requests[0]["content"]["parts"][0]["text"].startswith(
                "task: search result | query: "
            )
            for _ in range(2):
                with pytest.raises(EmbeddingUnavailable):
                    await client.query("other")
            assert len(requests) == 2  # Quota failures are not repeatedly retried.
            assert all("shoes" not in key for key in client.cache)

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Disposable pgvector required"
)
def test_hybrid_semantics_filters_fallback_and_invalidation():
    class FakeEmbeddings:
        fail = False

        async def query(self, text):
            if self.fail:
                raise EmbeddingUnavailable("offline")
            return vector_literal([1] + [0] * (DIMENSIONS - 1))

    async def run():
        async with shop() as (pool, _engines, ids, users):
            client = FakeEmbeddings()
            async with pool.connection() as connection:
                for product in ids:
                    await connection.execute(
                        "insert into public.product_embeddings(product_id,catalog_id,profile,content_hash,embedding) "
                        "values(%s,%s,%s,%s,%s::extensions.vector)",
                        (
                            product,
                            "00000000-0000-0000-0000-000000000001",
                            PROFILE,
                            "a" * 64,
                            await client.query(""),
                        ),
                    )
            catalog = Catalog(pool, embeddings=client)
            result = await catalog.search("comfortable all day")
            assert result["retrieval"] == "hybrid"
            assert {p["id"] for p in result["products"]} == set(ids)
            assert (await catalog.search("comfortable all day", max_price_paise=5000))[
                "products"
            ] == []
            limited = await catalog.search(
                "comfortable all day", max_price_paise=7000, exclude_ids=[ids[0]]
            )
            assert [p["id"] for p in limited["products"]] == [ids[1]]
            assert (await catalog.search("comfortable all day", exclude_ids=ids))[
                "products"
            ] == []
            other = Catalog(pool, catalog_id=users[1], embeddings=client)
            assert (await other.search("comfortable all day"))["products"] == []
            assert (await catalog.search("comfort -shirt"))["products"] == []
            assert (await catalog.search("comfort", category="Unknown category"))[
                "products"
            ] == []
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.demo_inventory set available=0 where product_id=%s",
                    (ids[0],),
                )
            stock = await catalog.search(
                "comfortable all day", availability="available"
            )
            assert [p["id"] for p in stock["products"]] == [ids[1]]
            client.fail = True
            fallback = await catalog.search("shirt")
            assert fallback["status"] == "ok" and fallback["retrieval"] == "keyword"
            assert fallback["retrieval_fallback"] == "embedding_unavailable"
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.products set product_name=%s where uniq_id=%s",
                    ("Different item", ids[0]),
                )
                cursor = await connection.execute(
                    "select count(*) from public.product_embeddings where product_id=%s",
                    (ids[0],),
                )
                assert (await cursor.fetchone())["count"] == 0

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Disposable pgvector required"
)
def test_indexer_is_bounded_and_resumable(monkeypatch, capsys):
    from psycopg_pool import AsyncConnectionPool

    from scripts import index_embeddings

    index = index_embeddings.run
    # Disposable local DB intentionally has no TLS; production pool stays TLS-only.
    monkeypatch.setattr(
        index_embeddings,
        "create_pool",
        lambda url: AsyncConnectionPool(url, open=False),
    )

    calls = []

    async def fake_embed(self, text):
        calls.append(text)
        return vector_literal([1] + [0] * (DIMENSIONS - 1))

    monkeypatch.setattr(GeminiEmbeddings, "embed", fake_embed)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")

    async def run():
        async with shop():
            args = argparse.Namespace(catalog=DEFAULT_CATALOG, limit=1, delay=0)
            assert await index(args) == 2
            assert len(calls) == 1
            assert await index(args) == 0
            assert len(calls) == 2
            assert await index(args) == 0
            assert len(calls) == 2

    asyncio.run(run())
    assert '"unchanged": 2' in capsys.readouterr().out
