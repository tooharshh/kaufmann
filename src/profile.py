import asyncio
import json
import re
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

import aiohttp

from src.auth import AuthFailure
from src.state.session import Refusal, address_patch, require_address

_locks = WeakValueDictionary()


def clean_text(value, limit):
    if (
        not isinstance(value, str)
        or len(value.strip()) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid_input")
    return value.strip()


def change_profile(current, operation, data):
    profile = {
        "name": "",
        "phone": "",
        "contact_email": "",
        "addresses": [],
        "default_address_id": None,
        **current,
    }
    if operation == "details":
        if set(data) - {"name", "phone", "contact_email"}:
            raise ValueError("invalid_input")
        for key, value in data.items():
            value = clean_text(
                value, 100 if key == "name" else 254 if key == "contact_email" else 30
            )
            if (
                key == "phone"
                and value
                and not re.fullmatch(r"\+?[0-9 ()-]{7,30}", value)
            ):
                raise ValueError("invalid_input")
            if (
                key == "contact_email"
                and value
                and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
            ):
                raise ValueError("invalid_input")
            profile[key] = value
    elif operation == "save_address":
        if set(data) - {"id", "label", "patch"} or "patch" not in data:
            raise ValueError("invalid_input")
        address_id = data.get("id")
        old = next((a for a in profile["addresses"] if a["id"] == address_id), None)
        if address_id and old is None:
            raise ValueError("not_found")
        if old is None and len(profile["addresses"]) >= 5:
            raise ValueError("address_limit")
        address = address_patch(old.get("address") if old else None, data["patch"])
        require_address(address)
        entry = {
            "id": address_id or str(uuid4()),
            "label": clean_text(data.get("label", old["label"] if old else "Home"), 40),
            "address": address,
        }
        profile["addresses"] = (
            [entry if a["id"] == address_id else a for a in profile["addresses"]]
            if old
            else [*profile["addresses"], entry]
        )
        if not profile["default_address_id"]:
            profile["default_address_id"] = entry["id"]
    elif operation in {"delete_address", "default_address"}:
        if set(data) != {"id"} or not any(
            a["id"] == data["id"] for a in profile["addresses"]
        ):
            raise ValueError("not_found")
        if operation == "delete_address":
            profile["addresses"] = [
                a for a in profile["addresses"] if a["id"] != data["id"]
            ]
            if profile["default_address_id"] == data["id"]:
                profile["default_address_id"] = (
                    profile["addresses"][0]["id"] if profile["addresses"] else None
                )
        else:
            profile["default_address_id"] = data["id"]
    else:
        raise ValueError("invalid_input")
    profile["revision"] = str(uuid4())
    if len(json.dumps(profile, ensure_ascii=False).encode()) > 4000:
        raise ValueError("profile_too_large")
    return profile


async def user_request(auth, authorization, owner, method="GET", data=None):
    try:
        async with auth.http.request(
            method,
            auth.url,
            headers={"Authorization": authorization, "apikey": auth.key},
            json=data,
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=False,
        ) as response:
            if response.status in {401, 403}:
                raise AuthFailure("unauthorized", 401)
            if response.status != 200:
                raise AuthFailure("auth_unavailable", 503)
            user = await response.json()
        if UUID(user["id"]) != owner:
            raise AuthFailure("unauthorized", 401)
        return user
    except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError):
        raise AuthFailure("auth_unavailable", 503) from None


def profile_view(user):
    metadata = user.get("user_metadata")
    value = metadata.get("kaufmann_profile") if isinstance(metadata, dict) else None
    profile = value if isinstance(value, dict) else {}
    addresses = []
    raw = profile.get("addresses", [])
    for entry in raw[:5] if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            identifier = str(UUID(entry["id"]))
            address = address_patch(None, entry["address"])
            require_address(address)
            label = clean_text(entry.get("label", "Home"), 40)
        except (ValueError, TypeError, KeyError, Refusal, AttributeError):
            continue
        addresses.append({"id": identifier, "label": label, "address": address})
    result = {}
    for key, limit in (("name", 100), ("phone", 30), ("contact_email", 254)):
        try:
            result[key] = clean_text(profile.get(key, ""), limit)
        except ValueError:
            result[key] = ""
    revision = profile.get("revision")
    return {
        **result,
        "addresses": addresses,
        "default_address_id": profile.get("default_address_id")
        if any(a["id"] == profile.get("default_address_id") for a in addresses)
        else None,
        "revision": revision
        if isinstance(revision, str) and len(revision) <= 64
        else None,
        "login_email": user.get("email", ""),
    }


async def update_profile(auth, authorization, owner, operation, data, revision):
    lock = _locks.setdefault(owner, asyncio.Lock())
    async with lock:
        user = await user_request(auth, authorization, owner)
        current = profile_view(user)
        if current["revision"] != revision:
            return {"status": "conflict", "profile": current}
        current.pop("login_email", None)
        try:
            profile = change_profile(current, operation, data)
        except Refusal as exc:
            return {"status": exc.status}
        except ValueError as exc:
            return {"status": str(exc)}
        user = await user_request(
            auth, authorization, owner, "PUT", {"data": {"kaufmann_profile": profile}}
        )
        return {"status": "ok", "profile": profile_view(user)}
