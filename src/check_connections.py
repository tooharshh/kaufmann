import asyncio
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import aiohttp
from livekit import api

from src.config import Settings
from src.db.connection import check_database


def request_status(url: str, headers: dict[str, str]) -> str:
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "kaufmann/0.1", **headers}), timeout=10
        ) as response:
            json.load(response)
        return "ok"
    except HTTPError as exc:
        return f"http_{exc.code}"
    except (OSError, ValueError):
        return "connection_failed"


async def check_livekit(settings: Settings) -> str:
    try:
        async with api.LiveKitAPI(
            settings["LIVEKIT_URL"],
            settings["LIVEKIT_API_KEY"],
            settings["LIVEKIT_API_SECRET"],
            timeout=aiohttp.ClientTimeout(total=10),
        ) as client:
            await client.room.list_rooms(api.ListRoomsRequest())
        return "ok"
    except (aiohttp.ClientError, api.TwirpError, TimeoutError, ValueError):
        return "connection_failed"


async def main() -> int:
    try:
        settings = Settings.load()
    except ValueError as exc:
        print(str(exc))
        return 1
    checks = {
        "cerebras": asyncio.to_thread(
            request_status,
            "https://api.cerebras.ai/v1/models",
            {"Authorization": "Bearer " + settings["CEREBRAS_API_KEY"]},
        ),
        "supabase_auth": asyncio.to_thread(
            request_status,
            settings["SUPABASE_URL"].rstrip("/") + "/auth/v1/settings",
            {"apikey": settings["SUPABASE_PUBLISHABLE_KEY"]},
        ),
        "livekit": check_livekit(settings),
        "database": check_database(settings["DATABASE_URL"]),
    }
    results = dict(zip(checks, await asyncio.gather(*checks.values()), strict=True))
    results["sarvam"] = "not_checked_no_speech_generated"
    print(json.dumps(results, indent=2))
    return int(any(results[name] != "ok" for name in checks))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
