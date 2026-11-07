import asyncio
import copy
import time

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from src.catalog.filters import (
    ATTRIBUTES,
    RATING_SQL,
    SORTS,
    attribute_pattern,
    filter_sql,
)
from src.catalog.products import product_result
from src.catalog.specifications import parse_specifications

SEARCH_SQL = """
with query as (select websearch_to_tsquery('english', %(query)s) as terms)
select p.*, i.available from public.products p
left join public.demo_inventory i on i.product_id = p.uniq_id cross join query
where discounted_price > 0
  and discounted_price <> 'NaN'::numeric
  and (%(availability)s = 'all' or (%(availability)s = 'available' and i.available > 0)
       or (%(availability)s = 'out_of_stock' and i.available = 0)
       or (%(availability)s = 'unknown' and i.available is null)
       or (%(availability)s = 'discoverable' and (i.available is null or i.available > 0)))
  and (%(query)s = '' or to_tsvector('english',
      coalesce(product_name, '') || ' ' || coalesce(product_category_tree, '')
  ) @@ query.terms)
  and (%(category)s = '' or position(
      lower(%(category)s) in lower(coalesce(product_category_tree, ''))
  ) > 0)
  and (%(max_price)s::numeric is null or discounted_price <= %(max_price)s::numeric / 100)
  and (%(min_price)s::numeric is null or discounted_price >= %(min_price)s::numeric / 100)
__FACETS__
  and (%(min_rating)s::numeric is null or (__RATING__) >= %(min_rating)s::numeric)
order by case when %(sort_by)s = 'price_asc' then discounted_price end asc,
case when %(sort_by)s = 'price_desc' then discounted_price end desc,
case when %(sort_by)s = 'rating_desc' then (__RATING__) end desc nulls last,
case when %(sort_by)s = 'newest' then crawl_timestamp end desc nulls last,
ts_rank(to_tsvector('english',
    coalesce(product_name, '') || ' ' || coalesce(product_category_tree, '')
), query.terms) desc, discounted_price, uniq_id
limit %(limit)s offset %(offset)s
""".replace("__FACETS__", filter_sql()).replace("__RATING__", RATING_SQL)


class Catalog:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool
        self._filter_cache = None
        self._filter_expires = 0
        self._filter_lock = asyncio.Lock()

    async def _fetch(self, query: str, params: dict) -> list[dict] | None:
        try:
            async with (
                asyncio.timeout(8),
                self.pool.connection(timeout=3) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                await cursor.execute("set local statement_timeout = '5s'")
                await cursor.execute(query, params)
                return await cursor.fetchall()
        except (psycopg.Error, PoolTimeout, TimeoutError):
            return None

    async def search(
        self,
        query: str = "",
        *,
        category: str = "",
        max_price_paise: int | None = None,
        min_price_paise: int | None = None,
        sort_by: str = "relevance",
        filters: dict[str, str] | None = None,
        min_rating: float | None = None,
        availability: str = "discoverable",
        limit: int = 5,
        offset: int = 0,
    ) -> dict:
        filters = {} if filters is None else filters
        if (
            not isinstance(filters, dict)
            or any(
                key not in ATTRIBUTES or not isinstance(value, str) or len(value) > 100
                for key, value in filters.items()
            )
            or availability
            not in ("discoverable", "all", "available", "out_of_stock", "unknown")
            or (
                min_rating is not None
                and (type(min_rating) not in (int, float) or not 0 <= min_rating <= 5)
            )
            or not isinstance(query, str)
            or not isinstance(category, str)
            or len(query) > 200
            or len(category) > 100
            or type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 100000
            or sort_by not in SORTS
            or (
                min_price_paise is not None
                and (
                    type(min_price_paise) is not int
                    or not 0 <= min_price_paise < 10**16
                )
            )
            or (
                type(min_price_paise) is int
                and type(max_price_paise) is int
                and min_price_paise > max_price_paise
            )
            or (
                max_price_paise is not None
                and (
                    type(max_price_paise) is not int or not 0 < max_price_paise < 10**16
                )
            )
        ):
            return {"status": "invalid_input", "products": []}
        rows = await self._fetch(
            SEARCH_SQL,
            {
                "query": query.strip(),
                "category": category.strip(),
                "max_price": max_price_paise,
                "min_price": min_price_paise,
                "sort_by": sort_by,
                "availability": availability,
                "min_rating": min_rating,
                **{name: filters.get(name, "").strip() for name in ATTRIBUTES},
                **{
                    name + "_pattern": attribute_pattern(name, filters.get(name, ""))
                    for name in ATTRIBUTES
                },
                "limit": limit + 1,
                "offset": offset,
            },
        )
        if rows is None:
            return {"status": "unavailable", "products": []}
        return {
            "status": "ok" if rows else "not_found",
            "products": [product_result(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
            "offset": offset,
        }

    async def filter_options(self):
        async with self._filter_lock:
            if (
                self._filter_cache is not None
                and time.monotonic() < self._filter_expires
            ):
                return copy.deepcopy(self._filter_cache)
            result = await self._load_filter_options()
            if result["status"] == "ok":
                self._filter_cache = result
                self._filter_expires = time.monotonic() + 300
            return copy.deepcopy(result)

    async def _load_filter_options(self):

        rows = await self._fetch(
            "select product_category_tree, product_specifications from public.products limit 50000",
            {},
        )
        if rows is None:
            return {"status": "unavailable", "filters": {}}
        return await asyncio.to_thread(self._parse_filter_options, rows)

    @staticmethod
    def _parse_filter_options(rows):
        from collections import Counter

        from src.catalog.ingest import parse_list

        values = {name: Counter() for name in ATTRIBUTES}
        categories = Counter()
        for row in rows:
            for path in parse_list(row.get("product_category_tree") or ""):
                categories[path.split(" >> ")[0]] += 1
            for key, entries in parse_specifications(
                row.get("product_specifications")
            ).items():
                for name, aliases in ATTRIBUTES.items():
                    if key.casefold() in aliases:
                        values[name].update(
                            value for value in entries if len(value) <= 100
                        )
        return {
            "status": "ok",
            "filters": {
                name: [value for value, _ in counter.most_common(60)]
                for name, counter in values.items()
            },
            "categories": [value for value, _ in categories.most_common(100)],
            "sorts": list(SORTS),
            "basis": "listed_specifications_not_variant_stock",
        }

    async def get(self, product_id: str) -> dict:
        if (
            not isinstance(product_id, str)
            or not product_id.strip()
            or len(product_id) > 128
        ):
            return {"status": "invalid_input", "product": None}
        rows = await self._fetch(
            "select p.*, i.available from public.products p left join public.demo_inventory i "
            "on i.product_id = p.uniq_id where p.uniq_id = %(id)s",
            {"id": product_id.strip()},
        )
        if rows is None:
            return {"status": "unavailable", "product": None}
        return {
            "status": "ok" if rows else "not_found",
            "product": product_result(rows[0], details=True) if rows else None,
        }

    async def compare(
        self,
        product_ids: list[str],
        *,
        attributes: list[str] | None = None,
    ) -> dict:
        empty = {"products": [], "attributes": []}
        if (
            not isinstance(product_ids, list)
            or not 2 <= len(product_ids) <= 4
            or any(
                not isinstance(p, str) or not p.strip() or len(p) > 128
                for p in product_ids
            )
            or (
                attributes is not None
                and (
                    not isinstance(attributes, list)
                    or not 1 <= len(attributes) <= 10
                    or any(
                        not isinstance(a, str) or not a.strip() or len(a) > 80
                        for a in attributes
                    )
                )
            )
        ):
            return {"status": "invalid_input", **empty}
        ids = [p.strip() for p in product_ids]
        if len(set(ids)) != len(ids):
            return {"status": "invalid_input", **empty}
        rows = await self._fetch(
            "select p.*, i.available from public.products p left join public.demo_inventory i "
            "on i.product_id = p.uniq_id where p.uniq_id = any(%(ids)s)",
            {"ids": ids},
        )
        if rows is None:
            return {"status": "unavailable", **empty}
        by_id = {row["uniq_id"]: row for row in rows}
        missing = [product_id for product_id in ids if product_id not in by_id]
        if missing:
            return {"status": "not_found", "missing_ids": missing, **empty}
        products = [product_result(by_id[product_id]) for product_id in ids]
        specs = {
            product_id: {
                name.casefold(): (name, values)
                for name, values in parse_specifications(
                    by_id[product_id].get("product_specifications")
                ).items()
            }
            for product_id in ids
        }
        names = {}
        for product_id in ids:
            for key, (name, _) in specs[product_id].items():
                names.setdefault(key, name)
        if attributes is not None:
            keys = list(
                dict.fromkeys(" ".join(a.split()).casefold() for a in attributes)
            )
            for attribute in attributes:
                names.setdefault(
                    " ".join(attribute.split()).casefold(), attribute.strip()
                )
        else:
            keys = sorted(
                names, key=lambda key: (-sum(key in specs[p] for p in ids), key)
            )[:12]
        prices = [product["price_paise"] for product in products]
        known = all(price is not None for price in prices)
        return {
            "status": "ok",
            "products": products,
            "attributes": [
                {
                    "name": names[key],
                    "values": {
                        p: specs[p][key][1] if key in specs[p] else None for p in ids
                    },
                }
                for key in keys
            ],
            "specification_basis": "historical_catalog",
            "price_difference_paise": max(prices) - min(prices) if known else None,
            "lowest_priced_ids": [
                p["id"] for p in products if p["price_paise"] == min(prices)
            ]
            if known
            else None,
        }
