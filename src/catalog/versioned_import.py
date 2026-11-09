"""Operator-only, staged CSV/JSON catalog import. No unconfigured currency or stock."""

import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb


def validate_catalog(source: Path, mapping: dict):
    fields = mapping.get("fields", {})
    if (
        not isinstance(fields, dict)
        or not {"id", "name", "price"} <= fields.keys()
        or mapping.get("price_unit") not in {"rupees", "paise"}
    ):
        raise ValueError(
            "Map id, name and price and declare price_unit rupees or paise"
        )
    if "currency" not in fields and mapping.get("currency") != "INR":
        raise ValueError("Declare currency INR or map a currency field")
    if any(not isinstance(v, str) or not v for v in fields.values()):
        raise ValueError("Field mappings must name source columns")
    if mapping.get("demo_inventory") is not None and (
        type(mapping["demo_inventory"]) is not int
        or not 0 <= mapping["demo_inventory"] <= 1000000
    ):
        raise ValueError("Invalid demo_inventory policy")
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = (
            list(csv.DictReader(handle))
            if source.suffix.lower() == ".csv"
            else json.load(handle)
        )
    if not isinstance(rows, list) or not rows or len(rows) > 100000:
        raise ValueError("Expected one to 100000 product rows")
    accepted, rejected, seen = [], [], set()
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict):
                raise TypeError("invalid_row")
            product = {key: row.get(column) for key, column in fields.items()}
            for key in ("id", "name"):
                if (
                    not isinstance(product.get(key), str)
                    or not product[key].strip()
                    or len(product[key]) > (128 if key == "id" else 500)
                ):
                    raise ValueError("missing_identity")
                product[key] = product[key].strip()
            if product["id"] in seen:
                raise ValueError("duplicate_id")
            seen.add(product["id"])
            price = Decimal(str(product["price"])) * (
                100 if mapping["price_unit"] == "rupees" else 1
            )
            if (
                not price.is_finite()
                or price <= 0
                or price != price.to_integral_value()
                or price >= 10**14
            ):
                raise ValueError("invalid_price")
            product["price_paise"] = int(price)
            if product.get("currency", mapping.get("currency")) != "INR":
                raise ValueError("unsupported_currency")
            stock = product.get("stock")
            if stock in (None, ""):
                product["stock"] = mapping.get("demo_inventory")
                product["stock_basis"] = (
                    "demo" if product["stock"] is not None else "unknown"
                )
            else:
                number = Decimal(str(stock))
                if (
                    isinstance(stock, bool)
                    or not number.is_finite()
                    or number != number.to_integral_value()
                    or not 0 <= number <= 1000000
                ):
                    raise ValueError("invalid_stock")
                product["stock"] = int(number)
                product["stock_basis"] = "source"
            for key, default, kind in (
                ("attributes", {}, dict),
                ("images", [], list),
                ("variants", [], list),
            ):
                value = product.get(key)
                value = json.loads(value) if isinstance(value, str) and value else value
                value = default if value is None or value == "" else value
                if not isinstance(value, kind):
                    raise TypeError("malformed_" + key)
                product[key] = value
            attributes = {}
            for key, value in product["attributes"].items():
                if not isinstance(key, str) or not 1 <= len(key) <= 80:
                    raise ValueError("malformed_attributes")
                entries = value if isinstance(value, list) else [value]
                if (
                    not entries
                    or len(entries) > 20
                    or any(
                        not isinstance(v, str) or not v.strip() or len(v) > 200
                        for v in entries
                    )
                ):
                    raise ValueError("malformed_attributes")
                attributes[key] = entries
            product["attributes"] = attributes
            if any(
                not isinstance(v, str)
                or len(v) > 2000
                or not v.startswith(("https://", "http://"))
                for v in product["images"]
            ):
                raise ValueError("malformed_images")
            for key, limit in (
                ("category", 1000),
                ("description", 8000),
                ("brand", 200),
                ("name_te", 500),
            ):
                value = product.get(key)
                if value is not None and (
                    not isinstance(value, str) or len(value) > limit
                ):
                    raise ValueError("invalid_" + key)
            product["source_row"] = index
            accepted.append(product)
        except (ValueError, TypeError, InvalidOperation) as exc:
            rejected.append(
                {
                    "row": index,
                    "reason": str(exc)
                    if isinstance(exc, ValueError)
                    else "invalid_value",
                }
            )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return (
        accepted,
        rejected,
        {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "source_sha256": digest,
            "mapping": mapping,
        },
    )


async def import_version(connection, name, products, rejected, report):
    if rejected or not products:
        raise ValueError("Import refused: resolve all rejected rows before activation")
    catalog_id = uuid4()
    async with connection.transaction():
        await connection.execute(
            "insert into public.catalog_versions(id, name, provenance) values (%s, %s, %s)",
            (catalog_id, name, Jsonb(report)),
        )
        for p in products:
            internal_id = f"{catalog_id}:{p['id']}"
            if len(internal_id) > 128:
                internal_id = (
                    f"{catalog_id}:{hashlib.sha256(p['id'].encode()).hexdigest()}"
                )
            specs = {
                "product_specification": [
                    {"key": k, "value": v}
                    for k, entries in p["attributes"].items()
                    for v in entries
                ]
            }
            await connection.execute(
                "insert into public.products(uniq_id, catalog_id, source_product_id, product_name, discounted_price, product_category_tree, name_te, description, brand, attributes, variants, image, product_specifications, provenance) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    internal_id,
                    catalog_id,
                    p["id"],
                    p["name"],
                    Decimal(p["price_paise"]) / 100,
                    json.dumps([p["category"]]) if p.get("category") else None,
                    p.get("name_te"),
                    p.get("description"),
                    p.get("brand"),
                    Jsonb(p["attributes"]),
                    Jsonb(p["variants"]),
                    json.dumps(p["images"]),
                    json.dumps(specs),
                    Jsonb(
                        {
                            "source_sha256": report["source_sha256"],
                            "row": p["source_row"],
                        }
                    ),
                ),
            )
            if p["stock"] is not None:
                await connection.execute(
                    "insert into public.demo_inventory(product_id, available, is_demo) values (%s,%s,%s)",
                    (internal_id, p["stock"], p["stock_basis"] == "demo"),
                )
        await connection.execute(
            "update public.catalog_versions set status = 'ready' where id = %s",
            (catalog_id,),
        )
    return catalog_id
