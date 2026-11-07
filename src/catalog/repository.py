from psycopg import AsyncConnection

COLUMNS = (
    "uniq_id",
    "crawl_timestamp",
    "product_url",
    "product_name",
    "product_category_tree",
    "pid",
    "retail_price",
    "discounted_price",
    "image",
    "is_FK_Advantage_product",
    "product_rating",
    "overall_rating",
    "product_specifications",
)


async def import_products(connection: AsyncConnection, products: list[dict]) -> int:
    if not products:
        return 0
    columns = ", ".join(f'"{column}"' for column in COLUMNS)
    updates = ", ".join(
        f'"{column}" = excluded."{column}"' for column in COLUMNS if column != "uniq_id"
    )
    async with connection.transaction():
        await connection.execute(
            "create temp table catalog_import "
            "(like public.products including defaults) on commit drop"
        )
        async with connection.cursor() as cursor:
            async with cursor.copy(
                f"copy catalog_import ({columns}) from stdin"
            ) as copy:
                for product in products:
                    row = product["source"]["row"]
                    await copy.write_row(
                        tuple(row.get(column) or None for column in COLUMNS)
                    )
            await cursor.execute(
                f"insert into public.products ({columns}) "
                f"select {columns} from catalog_import "
                f"on conflict (uniq_id) do update set {updates}"
            )
            count = cursor.rowcount
            await cursor.execute("drop table pg_temp.catalog_import")
            return count
