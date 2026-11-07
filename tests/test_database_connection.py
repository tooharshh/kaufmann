import asyncio

import psycopg

from src.db.connection import check_database


def test_connection_errors_are_classified_without_leaking_credentials(monkeypatch):
    async def run():
        for error, status in (
            (TimeoutError("private credentials"), "connection_timeout"),
            (
                psycopg.errors.InvalidPassword("private credentials"),
                "authentication_failed",
            ),
            (psycopg.OperationalError("private credentials"), "connection_failed"),
        ):

            async def fail(*args, error=error, **kwargs):
                raise error

            monkeypatch.setattr(psycopg.AsyncConnection, "connect", fail)
            assert await check_database("postgresql://private") == status

    asyncio.run(run())
