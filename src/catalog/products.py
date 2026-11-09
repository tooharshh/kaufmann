from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit

from src.catalog.ingest import parse_list, parse_price
from src.catalog.specifications import parse_specifications


def product_images(raw: str) -> list[str]:
    images = []
    for value in parse_list(raw):
        try:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
            ):
                continue
            if url.hostname in {
                "img5a.flixcart.com",
                "img6a.flixcart.com",
            } and url.path.startswith("/image/"):
                url = url._replace(scheme="https", netloc="rukminim2.flixcart.com")
            elif url.hostname.endswith(".flixcart.com"):
                url = url._replace(scheme="https")
            normalized = urlunsplit(url)
            if normalized not in images:
                images.append(normalized)
        except (ValueError, TypeError):
            continue
    return images[:3]


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
        "name_te": row.get("name_te"),
        "catalog_id": str(
            row.get("catalog_id", "00000000-0000-0000-0000-000000000001")
        ),
        "source_product_id": row.get("source_product_id") or row["uniq_id"],
        "brand": row.get("brand"),
        "description": row.get("description"),
        "attributes": row.get("attributes", {}),
        "variants": row.get("variants"),
        "category_path": categories[0].split(" >> ") if categories else [],
        "price_paise": price,
        "currency": "INR",
        "price_basis": "imported_catalog"
        if row.get("provenance")
        else "historical_catalog",
        "price_status": "priced" if price is not None else "unpriced",
        "stock_status": ("available" if row["available"] > 0 else "out_of_stock")
        if row.get("available") is not None
        else "unknown",
        "available_quantity": row.get("available"),
        "stock_basis": ("demo" if row.get("is_demo", True) else "source")
        if row.get("available") is not None
        else "unknown",
        "rating": rating,
        "images": product_images(row.get("image") or ""),
    }
    if details:
        result["specifications"] = parse_specifications(
            row.get("product_specifications")
        )
        result["specification_basis"] = result["price_basis"]
        result["specifications_raw"] = row.get("product_specifications")
        result["product_url"] = row.get("product_url")
        timestamp = row.get("crawl_timestamp")
        result["crawled_at"] = timestamp.isoformat() if timestamp else None
    return result
