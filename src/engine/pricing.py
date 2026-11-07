from src.catalog.ingest import parse_price
from src.state.session import Refusal, fingerprint


def cart_item(row: dict) -> dict:
    try:
        price = parse_price(str(row["discounted_price"]))
    except ValueError:
        price = None
    return {
        "product_id": row["product_id"],
        "name": row["product_name"],
        "quantity": row["quantity"],
        "unit_price_paise": price,
        "line_total_paise": price * row["quantity"] if price is not None else None,
        "available": row["available"],
        "stock_basis": "demo" if row["available"] is not None else "unknown",
    }


def quote(items: list[dict], *, check_stock: bool = True) -> dict:
    for item in items:
        if item["unit_price_paise"] is None:
            raise Refusal("unpriced")
        if check_stock and item["available"] is None:
            raise Refusal("inventory_unknown")
        if check_stock and item["quantity"] > item["available"]:
            raise Refusal("out_of_stock")
    if sum(item["line_total_paise"] for item in items) >= 2**63:
        raise Refusal("amount_out_of_range")
    return {
        "items": [
            {
                key: item[key]
                for key in (
                    "product_id",
                    "name",
                    "quantity",
                    "unit_price_paise",
                    "line_total_paise",
                )
            }
            for item in items
        ],
        "total_paise": sum(item["line_total_paise"] for item in items),
        "currency": "INR",
        "price_basis": "historical_catalog",
        "is_demo": True,
    }


def budget_digest(snapshot: dict, budget: int | None) -> str:
    return fingerprint({"cart": snapshot, "budget_paise": budget})
