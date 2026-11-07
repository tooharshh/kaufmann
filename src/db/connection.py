import asyncio

import psycopg
from psycopg_pool import AsyncConnectionPool


def create_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=4,
        timeout=10,
        open=False,
        kwargs={"connect_timeout": 10, "sslmode": "require", "prepare_threshold": None},
    )


async def check_database(database_url: str) -> str:
    try:
        async with (
            asyncio.timeout(15),
            await psycopg.AsyncConnection.connect(
                database_url,
                connect_timeout=10,
                sslmode="require",
                options="-c default_transaction_read_only=on -c statement_timeout=10000",
            ) as connection,
        ):
            await connection.execute("select 1")
        return "ok"
    except psycopg.errors.InvalidPassword:
        return "authentication_failed"
    except TimeoutError:
        return "connection_timeout"
    except psycopg.Error as exc:
        if "timeout" in str(exc).lower():
            return "connection_timeout"
        return "connection_failed"
