import csv

import pytest

from src.catalog.ingest import parse_price, prepare_catalog


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "-1", "0", "1.001"])
def test_reject_invalid_price(value):
    with pytest.raises(ValueError):
        parse_price(value)


def test_catalog_preserves_listing_identity_and_reports_rejections(tmp_path):
    source = tmp_path / "catalog.csv"
    fields = ["uniq_id", "product_name", "product_category_tree", "discounted_price"]
    rows = [
        ["a", "Shirt", '["Clothing >> Shirts"]', "199.99"],
        ["b", "Shirt", '["Clothing >> Shirts"]', "299"],
        ["a", "Duplicate", '["Clothing >> Shirts"]', "199.99"],
        ["c", "Unpriced", '["Clothing >> Shirts"]', ""],
    ]
    with source.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)
    products, rejected, report = prepare_catalog(source)
    assert [p["id"] for p in products] == ["a", "b"]
    assert products[0]["price_paise"] == 19999
    assert products[0]["category_path"] == ["Clothing", "Shirts"]
    assert products[0]["name_te"] is None
    assert "stock" not in products[0]
    assert report["accepted"] == report["rejected"] == len(rejected) == 2
    assert report["rejection_reasons"] == {"duplicate_id": 1, "invalid_price": 1}
