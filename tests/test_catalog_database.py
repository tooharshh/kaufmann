import asyncio
import os
from decimal import Decimal

import psycopg
import pytest

from src.catalog.ingest import normalize
from src.catalog.repository import import_products

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set TEST_DATABASE_URL")


def product(product_id, price=19999):
    return normalize(
        {
            "uniq_id": product_id,
            "product_name": "Test shirt",
            "product_category_tree": '["Clothing >> Shirts"]',
            "discounted_price": str(price / 100),
        }
    )


def test_import_retry_updates_price_and_preserves_other_products():
    async def run():
        async with (
            await psycopg.AsyncConnection.connect(DATABASE_URL) as connection,
            connection.transaction(force_rollback=True),
        ):
            assert (
                await import_products(
                    connection, [product("test-a"), product("test-b")]
                )
                == 2
            )
            assert await import_products(connection, [product("test-a", 29999)]) == 1
            cursor = await connection.execute(
                "select uniq_id, discounted_price from public.products "
                "where uniq_id in ('test-a', 'test-b') order by uniq_id"
            )
            assert await cursor.fetchall() == [
                ("test-a", Decimal("299.99")),
                ("test-b", Decimal("199.99")),
            ]

    asyncio.run(run())


def test_invalid_batch_rolls_back_and_browser_roles_cannot_write():
    async def run():
        async with (
            await psycopg.AsyncConnection.connect(DATABASE_URL) as connection,
            connection.transaction(force_rollback=True),
        ):
            with pytest.raises(psycopg.IntegrityError):
                await import_products(
                    connection,
                    [
                        product("test-good"),
                        dict(
                            product("test-bad"),
                            source={"row": {"uniq_id": "test-bad", "product_name": ""}},
                        ),
                    ],
                )
            cursor = await connection.execute(
                "select count(*) from public.products where uniq_id in ('test-good', 'test-bad')"
            )
            assert await cursor.fetchone() == (0,)
            await import_products(connection, [product("test-visible")])
            async with connection.transaction():
                await connection.execute("set local role authenticated")
                cursor = await connection.execute(
                    "select uniq_id from public.products where uniq_id = 'test-visible'"
                )
                assert await cursor.fetchone() == ("test-visible",)
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        await connection.execute(
                            "delete from public.products where false"
                        )
            await connection.execute("reset role")
            async with connection.transaction():
                await connection.execute("set local role anon")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        await connection.execute(
                            "select uniq_id from public.products limit 1"
                        )

    asyncio.run(run())
