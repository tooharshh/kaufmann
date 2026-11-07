import hashlib
import json
from uuid import UUID


class Refusal(Exception):
    def __init__(self, status: str):
        self.status = status


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def token_hash(token: str) -> str:
    if not isinstance(token, str) or not 16 <= len(token) <= 256:
        raise Refusal("invalid_token")
    return hashlib.sha256(token.encode()).hexdigest()


def valid_uuid(value) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise Refusal("invalid_input") from None


def address_patch(current: dict | None, patch: dict) -> dict:
    limits = {
        "recipient": 100,
        "line1": 200,
        "line2": 200,
        "city": 100,
        "state": 100,
        "postal_code": 6,
        "country": 2,
    }
    if not isinstance(patch, dict) or not patch or set(patch) - limits.keys():
        raise Refusal("invalid_address")
    result = dict(current or {})
    for key, value in patch.items():
        if not isinstance(value, str) or len(value.strip()) > limits[key]:
            raise Refusal("invalid_address")
        value = value.strip()
        if (
            key == "postal_code"
            and value
            and not (value.isascii() and value.isdecimal() and len(value) == 6)
        ):
            raise Refusal("invalid_address")
        if key == "country" and value != "IN":
            raise Refusal("invalid_address")
        result[key] = value
    result.setdefault("country", "IN")
    return result


def require_address(address: dict | None) -> None:
    if not address or any(
        not address.get(key)
        for key in ("recipient", "line1", "city", "state", "postal_code", "country")
    ):
        raise Refusal("address_required")
