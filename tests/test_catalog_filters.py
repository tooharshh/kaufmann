import asyncio
import json
import os

import pytest

from src.catalog.search import Catalog
from tests.test_commerce_engine import shop

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Local Postgres required"
)


def test_source_filters_stock_rating_and_sorting():
    async def run():
        async with shop() as (pool, _engines, products, _users):
            async with pool.connection() as connection:
                for index, (gender, size, rating) in enumerate(
                    (("Men's", "M", "4.5"), ("Women's", "XXL", "No rating available"))
                ):
                    specs = {
                        "product_specification": [
                            {"key": key, "value": value}
                            for key, value in {
                                "Color": "Navy Blue",
                                "Size": size,
                                "Ideal For": gender,
                                "Brand": "Test Brand",
                                "Fabric": "Cotton",
                                "Occasion": "Casual",
                            }.items()
                        ]
                    }
                    raw = json.dumps(specs)
                    if index == 0:
                        raw = raw.replace(":", "=>")
                    await connection.execute(
                        "update public.products set product_specifications=%s, product_rating=%s, product_category_tree=%s where uniq_id=%s",
                        (raw, rating, '["Clothing >> Shirts"]', products[index]),
                    )
                await connection.execute(
                    "update public.demo_inventory set available=0 where product_id=%s",
                    (products[1],),
                )
            catalog = Catalog(pool)
            result = await catalog.search(
                "shirt",
                filters={
                    "color": "blue",
                    "size": "medium",
                    "gender": "men",
                    "brand": "Test Brand",
                    "material": "cotton",
                },
                min_rating=4,
                availability="available",
            )
            assert [p["id"] for p in result["products"]] == [products[0]]
            assert (
                await catalog.search(
                    "shirt",
                    filters={"size": "M", "gender": "women"},
                    availability="all",
                )
            )["products"] == []
            assert (await catalog.search("shirt", filters={"brand": "Test"}))[
                "products"
            ] == []
            assert (await catalog.search("shirt", filters={"color": "blue.*"}))[
                "products"
            ] == []
            out = await catalog.search("shirt", availability="out_of_stock")
            assert [p["id"] for p in out["products"]] == [products[1]]
            rated = await catalog.search(
                "shirt", availability="all", sort_by="rating_desc"
            )
            assert [p["id"] for p in rated["products"]] == products
            costly = await catalog.search(
                "shirt", availability="all", sort_by="price_desc"
            )
            assert [p["id"] for p in costly["products"]] == products
            options = await catalog.filter_options()
            assert "Navy Blue" in options["filters"]["color"]
            assert "Clothing" in options["categories"]
            for filters in ({"color": ["blue"]},):
                assert (await catalog.search(filters=filters))[
                    "status"
                ] == "invalid_input"
            assert (await catalog.search(min_rating=float("nan")))[
                "status"
            ] == "invalid_input"

    asyncio.run(run())
