"""Bounded task state. Product facts must always be loaded from the catalog."""

import json

from src.state.session import Refusal


def discovery_task(value):
    if (
        not isinstance(value, dict)
        or set(value)
        - {
            "original_input",
            "constraints",
            "search_arguments",
            "rejected_ids",
            "selected_product_id",
        }
        or len(json.dumps(value, ensure_ascii=False)) > 12000
    ):
        raise Refusal("invalid_input")
    text = value.get("original_input", "")
    if not isinstance(text, str) or len(text) > 2000:
        raise Refusal("invalid_input")
    constraints = value.get("constraints", {})
    if not isinstance(constraints, dict) or set(constraints) - {
        "recipient",
        "requirements",
        "exclusions",
        "budget_paise",
        "product_type",
    }:
        raise Refusal("invalid_input")
    for key, item in constraints.items():
        if key == "budget_paise":
            valid = item is None or type(item) is int and 0 <= item < 10**16
        elif key in {"requirements", "exclusions"}:
            valid = (
                isinstance(item, list)
                and len(item) <= 20
                and all(isinstance(s, str) and len(s) <= 200 for s in item)
            )
        else:
            valid = isinstance(item, str) and len(item) <= 300
        if not valid:
            raise Refusal("invalid_input")
    arguments = value.get("search_arguments", {})
    if not isinstance(arguments, dict) or set(arguments) - {
        "query",
        "category",
        "max_price_paise",
        "min_price_paise",
        "sort_by",
        "filters",
        "min_rating",
        "availability",
        "limit",
        "offset",
        "exclude_ids",
    }:
        raise Refusal("invalid_input")
    ids = value.get("rejected_ids", [])
    selected = value.get("selected_product_id")
    if (
        not isinstance(ids, list)
        or len(ids) > 200
        or any(not isinstance(s, str) or not 1 <= len(s) <= 128 for s in ids)
        or (
            selected is not None
            and (not isinstance(selected, str) or not 1 <= len(selected) <= 128)
        )
    ):
        raise Refusal("invalid_input")
    return value
