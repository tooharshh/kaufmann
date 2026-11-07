import asyncio
import json
import socket
import sys
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Settings


async def main() -> int:
    params = conninfo_to_dict(Settings.load()["DATABASE_URL"])
    host, port = params["host"], int(params.get("port", 5432))
    result = {"port": port}
    try:
        await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=5,
        )
        result["dns"] = "ok"
    except (OSError, TimeoutError):
        result["dns"] = "failed"
        print(json.dumps(result))
        return 1
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
        result["tcp"] = "ok"
        writer.close()
        await writer.wait_closed()
    except TimeoutError:
        result["tcp"] = "timeout"
    except OSError:
        result["tcp"] = "failed"
    print(json.dumps(result))
    return int(result["tcp"] != "ok")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
