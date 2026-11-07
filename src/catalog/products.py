from decimal import Decimal, InvalidOperation

from src.catalog.ingest import parse_list, parse_price
from src.catalog.specifications import parse_specifications


def product_result(row: dict, *, details: bool = False) -> dict:
    try:
        price = parse_price(str(row["discounted_price"]))
    except ValueError:
        price = None
    categories = parse_list(row.get("product_category_tree") or "")
    rating = None
    try:
        value = Decimal(row.get("product_rating") or "")
        if value.is_finite() and 0 <= value <= 5:
            rating = float(value)
    except InvalidOperation:
        pass
    result = {
        "id": row["uniq_id"],
        "name": row["product_name"],
        "name_te": None,
        "category_path": categories[0].split(" >> ") if categories else [],
        "price_paise": price,
        "currency": "INR",
        "price_basis": "historical_catalog",
        "price_status": "priced" if price is not None else "unpriced",
        "stock_status": ("available" if row["available"] > 0 else "out_of_stock")
        if row.get("available") is not None
        else "unknown",
        "available_quantity": row.get("available"),
        "stock_basis": "demo" if row.get("available") is not None else "unknown",
        "rating": rating,
        "images": parse_list(row.get("image") or "")[:3],
    }
    if details:
        result["specifications"] = parse_specifications(
            row.get("product_specifications")
        )
        result["specification_basis"] = "historical_catalog"
        result["specifications_raw"] = row.get("product_specifications")
        result["product_url"] = row.get("product_url")
        timestamp = row.get("crawl_timestamp")
        result["crawled_at"] = timestamp.isoformat() if timestamp else None
    return result
