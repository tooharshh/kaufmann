import asyncio
import os

import pytest
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from src.catalog.ingest import normalize
from src.catalog.repository import import_products
from src.catalog.search import Catalog


def test_catalog_failure_does_not_return_products():
    class UnavailablePool:
        def connection(self, **kwargs):
            raise PoolTimeout("private connection details")

    async def run():
        catalog = Catalog(UnavailablePool())
        assert await catalog.search("shoes") == {
            "status": "unavailable",
            "products": [],
        }
        assert await catalog.get("missing") == {
            "status": "unavailable",
            "product": None,
        }

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_catalog_search_filters_and_unpriced_lookup():
    async def run():
        async with AsyncConnectionPool(
            os.environ["TEST_DATABASE_URL"], min_size=1, max_size=1
        ) as pool:
            async with pool.connection() as connection:
                rows = [
                    normalize(
                        {
                            "uniq_id": product_id,
                            "product_name": "Kaufmannfixture running shoes",
                            "product_category_tree": '["Footwear >> Running Shoes"]',
                            "discounted_price": price,
                        }
                    )
                    for product_id, price in (
                        ("search-cheap", "299.99"),
                        ("search-expensive", "1500"),
                    )
                ]
                await import_products(connection, rows)
                await connection.execute(
                    "insert into public.products (uniq_id, product_name) values (%s, %s)",
                    ("search-unpriced", "Kaufmannfixture shoes"),
                )
            try:
                catalog = Catalog(pool)
                result = await catalog.search(
                    "kaufmannfixture shoes", category="Footwear", max_price_paise=50000
                )
                assert result["status"] == "ok"
                assert [p["id"] for p in result["products"]] == ["search-cheap"]
                assert result["products"][0]["price_paise"] == 29999
                assert result["products"][0]["stock_status"] == "unknown"
                first = await catalog.search("kaufmannfixture", limit=1)
                second = await catalog.search("kaufmannfixture", limit=1, offset=1)
                assert first["has_more"]
                assert first["products"][0]["id"] == "search-cheap"
                assert second["products"][0]["id"] == "search-expensive"
                assert not second["has_more"]
                assert (await catalog.search("kaufmannfixture", category="Clothing"))[
                    "status"
                ] == "not_found"
                assert (await catalog.get("' OR true --"))["status"] == "not_found"
                lookup = await catalog.get("search-unpriced")
                assert lookup["product"]["price_status"] == "unpriced"
                assert lookup["product"]["price_paise"] is None
            finally:
                async with pool.connection() as connection:
                    await connection.execute(
                        "delete from public.products where uniq_id = any(%s)",
                        (["search-cheap", "search-expensive", "search-unpriced"],),
                    )

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_alternative_gift_types_keep_price_and_exclusion_constraints():
    async def run():
        async with AsyncConnectionPool(
            os.environ["TEST_DATABASE_URL"], min_size=1, max_size=1
        ) as pool:
            fixtures = [
                ("intent-mug", "Intentfixture ceramic mug", "250"),
                ("intent-frame", "Intentfixture photo frame", "450"),
                ("intent-luxury", "Intentfixture ceramic mug", "900"),
                ("intent-excluded", "Intentfixture jewellery photo frame", "200"),
            ]
            async with pool.connection() as connection:
                await import_products(
                    connection,
                    [
                        normalize(
                            {
                                "uniq_id": key,
                                "product_name": name,
                                "product_category_tree": '["Home >> Giftware"]',
                                "discounted_price": price,
                            }
                        )
                        for key, name, price in fixtures
                    ],
                )
            try:
                result = await Catalog(pool).search(
                    "intentfixture mug -jewellery OR intentfixture photo frame -jewellery",
                    max_price_paise=50000,
                )
                assert result["status"] == "ok"
                assert {p["id"] for p in result["products"]} == {
                    "intent-mug",
                    "intent-frame",
                }
                assert all(p["price_paise"] <= 50000 for p in result["products"])
                ranged = await Catalog(pool).search(
                    "intentfixture", min_price_paise=40000, max_price_paise=50000
                )
                assert [p["id"] for p in ranged["products"]] == ["intent-frame"]
                cheapest = await Catalog(pool).search(
                    "intentfixture mug OR intentfixture photo frame",
                    sort_by="price_asc",
                )
                assert [p["price_paise"] for p in cheapest["products"]] == [
                    20000,
                    25000,
                    45000,
                    90000,
                ]
                for arguments in (
                    {"min_price_paise": 50000, "max_price_paise": 10000},
                    {"min_price_paise": -1},
                    {"min_price_paise": True},
                    {"sort_by": "unknown"},
                ):
                    assert (await Catalog(pool).search("intentfixture", **arguments))[
                        "status"
                    ] == "invalid_input"
            finally:
                async with pool.connection() as connection:
                    await connection.execute(
                        "delete from public.products where uniq_id = any(%s)",
                        ([row[0] for row in fixtures],),
                    )

    asyncio.run(run())
