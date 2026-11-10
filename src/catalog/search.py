import asyncio
import copy
import re
import time

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from src.catalog.embeddings import PROFILE, EmbeddingUnavailable
from src.catalog.filters import (
    ATTRIBUTES,
    RATING_SQL,
    SORTS,
    attribute_pattern,
    filter_sql,
)
from src.catalog.products import product_result
from src.catalog.selection import DEFAULT_CATALOG, selected_catalog
from src.catalog.specifications import parse_specifications
from src.state.session import Refusal

SEARCH_SQL = """
with query as (select websearch_to_tsquery('english', %(query)s) as terms)
select p.*, i.available, i.is_demo from public.products p
left join public.demo_inventory i on i.product_id = p.uniq_id cross join query
where p.catalog_id = %(catalog_id)s
  and not (p.uniq_id = any(%(exclude_ids)s))
  and discounted_price > 0
  and discounted_price <> 'NaN'::numeric
  and (%(availability)s = 'all' or (%(availability)s = 'available' and i.available > 0)
       or (%(availability)s = 'out_of_stock' and i.available = 0)
       or (%(availability)s = 'unknown' and i.available is null)
       or (%(availability)s = 'discoverable' and (i.available is null or i.available > 0)))
  and (%(query)s = '' or p.search_document @@ query.terms)
  and (%(category)s = '' or position(
      lower(%(category)s) in lower(coalesce(product_category_tree, ''))
  ) > 0)
  and (%(max_price)s::numeric is null or discounted_price <= %(max_price)s::numeric / 100)
  and (%(min_price)s::numeric is null or discounted_price >= %(min_price)s::numeric / 100)
__FACETS__
  and not exists(select 1 from jsonb_each_text(%(extra_filters)s::jsonb) f
      where not exists(select 1 from jsonb_each(p.attributes) a
          where lower(a.key) = lower(f.key) and exists(select 1 from jsonb_array_elements_text(a.value) v where lower(v) = lower(f.value))))
  and (%(min_rating)s::numeric is null or (__RATING__) >= %(min_rating)s::numeric)
order by case when %(sort_by)s = 'price_asc' then discounted_price end asc,
case when %(sort_by)s = 'price_desc' then discounted_price end desc,
case when %(sort_by)s = 'rating_desc' then (__RATING__) end desc nulls last,
case when %(sort_by)s = 'newest' then crawl_timestamp end desc nulls last,
ts_rank(p.search_document, query.terms) desc, discounted_price, uniq_id
limit %(limit)s offset %(offset)s
""".replace("__FACETS__", filter_sql()).replace("__RATING__", RATING_SQL)

# Reuse the complete eligibility predicate: semantic similarity cannot bypass it.
_ELIGIBLE = (
    SEARCH_SQL.split("\norder by case")[0]
    .replace(
        "select p.*, i.available, i.is_demo",
        "select p.*, i.available, i.is_demo, ts_rank(p.search_document, query.terms) as lexical_score, (p.search_document @@ query.terms) as lexical_match",
    )
    .replace("  and (%(query)s = '' or p.search_document @@ query.terms)\n", "\n")
    .replace(
        "  and discounted_price > 0",
        "  and (%(negative_query)s = '' or not (p.search_document @@ websearch_to_tsquery('english', %(negative_query)s)))\n  and discounted_price > 0",
    )
)
_ELIGIBLE = _ELIGIBLE.split("\nselect ", 1)[1]
HYBRID_SQL = (
    """
with query as (select websearch_to_tsquery('english', %(query)s) as terms),
eligible as materialized (select """
    + _ELIGIBLE
    + """),
lexical as (
    select uniq_id, row_number() over(order by lexical_score desc, uniq_id) as rank
    from eligible where lexical_match order by lexical_score desc, uniq_id limit %(candidates)s
),
semantic as (
    select e.uniq_id, row_number() over(order by v.embedding OPERATOR(extensions.<=>) %(vector)s::extensions.vector, e.uniq_id) as rank
    from eligible e join public.product_embeddings v
      on v.product_id=e.uniq_id and v.catalog_id=e.catalog_id and v.profile=%(profile)s
    where (v.embedding OPERATOR(extensions.<=>) %(vector)s::extensions.vector) <= %(max_distance)s
    order by v.embedding OPERATOR(extensions.<=>) %(vector)s::extensions.vector, e.uniq_id limit %(candidates)s
),
scores as (
    select uniq_id, sum(score) as score from (
        select uniq_id, 1.0/(60+rank) as score from lexical
        union all select uniq_id, 1.0/(60+rank) from semantic
    ) ranked group by uniq_id
)
select e.* from eligible e join scores s using(uniq_id)
order by s.score desc, e.uniq_id
limit %(limit)s offset %(offset)s
"""
)


class Catalog:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        catalog_id=DEFAULT_CATALOG,
        user_id=None,
        generation=None,
        embeddings=None,
    ):
        self.catalog_id = catalog_id
        self.user_id = user_id
        self.generation = generation
        self.pool = pool
        self.embeddings = embeddings
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
                params = {**params, "catalog_id": self.catalog_id}
                if self.user_id is not None:
                    connection.row_factory = dict_row
                    selection = await selected_catalog(connection, self.user_id)
                    if (
                        selection["catalog_id"] != self.catalog_id
                        or self.generation is not None
                        and selection["generation"] != self.generation
                    ):
                        return None
                await cursor.execute("set local statement_timeout = '5s'")
                await cursor.execute(query, params)
                return await cursor.fetchall()
        except (psycopg.Error, PoolTimeout, TimeoutError, Refusal):
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
        exclude_ids: list[str] | None = None,
        semantic_query: str | None = None,
    ) -> dict:
        filters = {} if filters is None else filters
        exclude_ids = [] if exclude_ids is None else exclude_ids
        if (
            not isinstance(exclude_ids, list)
            or len(exclude_ids) > 200
            or any(
                not isinstance(p, str) or not 1 <= len(p) <= 128 for p in exclude_ids
            )
            or not isinstance(filters, dict)
            or any(
                not isinstance(key, str)
                or not 1 <= len(key) <= 80
                or not isinstance(value, str)
                or len(value) > 100
                for key, value in filters.items()
            )
            or availability
            not in ("discoverable", "all", "available", "out_of_stock", "unknown")
            or (
                min_rating is not None
                and (type(min_rating) not in (int, float) or not 0 <= min_rating <= 5)
            )
            or not isinstance(query, str)
            or (
                semantic_query is not None
                and (not isinstance(semantic_query, str) or len(semantic_query) > 500)
            )
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
        params = {
            "query": query.strip(),
            "exclude_ids": exclude_ids,
            "extra_filters": Jsonb(
                {key: value for key, value in filters.items() if key not in ATTRIBUTES}
            ),
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
        }
        retrieval = "keyword"
        fallback = None
        rows = None
        # Explicit price/rating/date sorts retain their original complete ordering.
        if self.embeddings and query.strip() and sort_by == "relevance":
            try:
                negatives = re.findall(r'(?:^|\s)-(?:"([^"]+)"|(\S+))', query)
                negative_query = " OR ".join(
                    '"' + (phrase or word).replace('"', "") + '"'
                    for phrase, word in negatives
                )
                async with asyncio.timeout(3.5):
                    vector = await self.embeddings.query(
                        (semantic_query or query).strip()
                    )
                rows = await self._fetch(
                    HYBRID_SQL,
                    {
                        **params,
                        "vector": vector,
                        "profile": PROFILE,
                        "candidates": 1000,
                        "max_distance": 0.45,
                        "negative_query": negative_query,
                    },
                )
                if rows is not None:
                    retrieval = "hybrid"
                else:
                    fallback = "semantic_index_unavailable"
            except (EmbeddingUnavailable, TimeoutError):
                fallback = "embedding_unavailable"
        if rows is None:
            rows = await self._fetch(SEARCH_SQL, params)
        if rows is None:
            return {"status": "unavailable", "products": []}
        return {
            "status": "ok" if rows else "not_found",
            "products": [product_result(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
            "offset": offset,
            "catalog_id": str(self.catalog_id),
            "retrieval": retrieval,
            "retrieval_fallback": fallback,
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
            "select product_category_tree, product_specifications from public.products where catalog_id = %(catalog_id)s limit 50000",
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
                if not any(
                    key.casefold() in aliases for aliases in ATTRIBUTES.values()
                ):
                    values.setdefault(key.casefold(), Counter()).update(
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
            "select p.*, i.available, i.is_demo from public.products p left join public.demo_inventory i "
            "on i.product_id = p.uniq_id where p.catalog_id = %(catalog_id)s and p.uniq_id = %(id)s",
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
            "select p.*, i.available, i.is_demo from public.products p left join public.demo_inventory i "
            "on i.product_id = p.uniq_id where p.catalog_id = %(catalog_id)s and p.uniq_id = any(%(ids)s)",
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
            "specification_basis": "catalog_source",
            "price_difference_paise": max(prices) - min(prices) if known else None,
            "lowest_priced_ids": [
                p["id"] for p in products if p["price_paise"] == min(prices)
            ]
            if known
            else None,
        }
