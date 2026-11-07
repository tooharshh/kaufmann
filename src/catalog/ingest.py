import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


def parse_price(value: str) -> int:
    try:
        amount = Decimal(value.strip())
        paise = amount * 100
        if not amount.is_finite() or amount <= 0 or paise != paise.to_integral_value():
            raise ValueError("invalid_price")
        return int(paise)
    except (InvalidOperation, AttributeError):
        raise ValueError("invalid_price") from None


def parse_list(value: str) -> list[str]:
    try:
        items = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def normalize(row: dict[str, str]) -> dict:
    product_id = row["uniq_id"].strip()
    name = row["product_name"].strip()
    if not product_id or not name:
        raise ValueError("missing_identity")
    categories = parse_list(row.get("product_category_tree", ""))
    if not categories:
        raise ValueError("missing_category")
    return {
        "id": product_id,
        "name": name,
        "name_te": None,
        "category_path": [part.strip() for part in categories[0].split(" >> ")],
        "brand": row.get("brand", "").strip() or None,
        "description": row.get("description", "").strip() or None,
        "price_paise": parse_price(row.get("discounted_price", "")),
        "currency": "INR",
        "images": parse_list(row.get("image", "")),
        "specifications_raw": row.get("product_specifications", ""),
        "source": {
            "row": dict(row),
            "dataset": "PromptCloudHQ/flipkart-products",
            "product_url": row.get("product_url", ""),
            "crawled_at": row.get("crawl_timestamp", ""),
            "retail_price_raw": row.get("retail_price", ""),
            "discounted_price_raw": row.get("discounted_price", ""),
        },
    }


def prepare_catalog(source: Path) -> tuple[list[dict], list[dict], dict]:
    products, rejected = [], []
    seen = set()
    categories = Counter()
    reasons = Counter()
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "uniq_id",
            "product_name",
            "product_category_tree",
            "discounted_price",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV is missing required catalog columns")
        for line, row in enumerate(reader, start=2):
            try:
                product = normalize(row)
                if product["id"] in seen:
                    raise ValueError("duplicate_id")
            except ValueError as exc:
                reason = str(exc)
                reasons[reason] += 1
                rejected.append(
                    {"line": line, "id": row.get("uniq_id"), "reason": reason}
                )
                continue
            seen.add(product["id"])
            products.append(product)
            categories[product["category_path"][0]] += 1
    report = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "accepted": len(products),
        "rejected": len(rejected),
        "rejection_reasons": dict(reasons),
        "categories": dict(sorted(categories.items())),
        "price_basis": "historical discounted price from source; no retail fallback",
        "stock": "not supplied by source; demo inventory policy pending",
        "telugu_names": "not supplied by source; pending translation",
    }
    return products, rejected, report
