import base64
import json
from uuid import UUID

import aiohttp


def public_auth_config(settings) -> dict:
    key = settings["SUPABASE_PUBLISHABLE_KEY"]
    public = key.startswith("sb_publishable_")
    if not public and key.count(".") == 2:
        try:
            payload = key.split(".")[1]
            public = (
                json.loads(
                    base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
                ).get("role")
                == "anon"
            )
        except (ValueError, AttributeError, UnicodeError):
            public = False
    if not public:
        raise AuthFailure("configuration_unavailable", 503)
    return {
        "status": "ok",
        "supabase_url": settings["SUPABASE_URL"],
        "publishable_key": key,
    }


class AuthFailure(Exception):
    def __init__(self, status: str, http_status: int):
        self.status = status
        self.http_status = http_status


class SupabaseAuth:
    def __init__(self, http: aiohttp.ClientSession, url: str, publishable_key: str):
        self.http = http
        self.url = url.rstrip("/") + "/auth/v1/user"
        self.key = publishable_key

    async def authenticate(self, authorization: str | None) -> UUID:
        scheme, _, token = (authorization or "").partition(" ")
        if (
            scheme.lower() != "bearer"
            or not token
            or len(token) > 8192
            or not token.isascii()
            or any(c.isspace() for c in token)
        ):
            raise AuthFailure("unauthorized", 401)
        try:
            async with self.http.get(
                self.url,
                headers={"Authorization": "Bearer " + token, "apikey": self.key},
                timeout=aiohttp.ClientTimeout(total=5),
                allow_redirects=False,
            ) as response:
                if response.status in {401, 403}:
                    raise AuthFailure("unauthorized", 401)
                if response.status != 200:
                    raise AuthFailure("auth_unavailable", 503)
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise AuthFailure("auth_unavailable", 503) from None
        if not isinstance(data, dict):
            raise AuthFailure("auth_unavailable", 503)
        if data.get("is_anonymous"):
            raise AuthFailure("sign_in_required", 403)
        try:
            return UUID(data["id"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AuthFailure("auth_unavailable", 503) from None
