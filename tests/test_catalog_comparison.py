import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

from src.catalog.search import Catalog
from src.catalog.specifications import parse_specifications


def test_source_specifications_preserve_values_and_ignore_unlabeled_entries():
    raw = '{"product_specification"=>[{"key"=>"Fabric", "value"=>"Cotton => blend"}, {"key"=>"fabric", "value"=>"Linen"}, {"value"=>"Unlabeled"}]}'
    assert parse_specifications(raw) == {"Fabric": ["Cotton => blend", "Linen"]}
    assert parse_specifications('{"product_specification"=>invalid}') == {}


def test_comparison_preserves_order_missing_facts_and_exact_prices():
    async def run():
        catalog = Catalog(None)
        rows = [
            {
                "uniq_id": product_id,
                "product_name": "Shirt",
                "discounted_price": price,
                "product_specifications": '{"product_specification"=>[{"key"=>"Fabric", "value"=>"Cotton"}]}',
            }
            for product_id, price in (
                ("b", Decimal("299.99")),
                ("a", Decimal("199.99")),
            )
        ]
        catalog._fetch = AsyncMock(return_value=rows)
        result = await catalog.compare(["a", "b"], attributes=["Fabric", "Warranty"])
        assert result["status"] == "ok"
        assert [p["id"] for p in result["products"]] == ["a", "b"]
        assert result["price_difference_paise"] == 10000
        assert result["lowest_priced_ids"] == ["a"]
        assert result["attributes"][0]["values"] == {"a": ["Cotton"], "b": ["Cotton"]}
        assert result["attributes"][1]["values"] == {"a": None, "b": None}
        assert all(p["stock_status"] == "unknown" for p in result["products"])
        rows[0]["discounted_price"] = None
        result = await catalog.compare(["a", "b"])
        assert result["price_difference_paise"] is None
        assert result["lowest_priced_ids"] is None
        result = await catalog.compare(["a", "missing"])
        assert result["status"] == "not_found"
        assert result["products"] == []
        assert result["missing_ids"] == ["missing"]

    asyncio.run(run())
