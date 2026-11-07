import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.engine.cart import CommerceEngine

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set TEST_DATABASE_URL")
ADDRESS = {
    "recipient": "Demo Shopper",
    "line1": "12 Test Road",
    "city": "Hyderabad",
    "state": "Telangana",
    "postal_code": "500001",
    "country": "IN",
}


@asynccontextmanager
async def shop():
    assert conninfo_to_dict(DATABASE_URL).get("host") in {"localhost", "127.0.0.1"}
    users = [uuid4(), uuid4()]
    products = [str(uuid4()), str(uuid4())]
    async with AsyncConnectionPool(
        DATABASE_URL, min_size=1, max_size=4, kwargs={"row_factory": dict_row}
    ) as pool:
        async with pool.connection() as connection:
            for user in users:
                await connection.execute(
                    "insert into auth.users (id) values (%s)", (user,)
                )
            for product, price in zip(products, (100, 60), strict=True):
                await connection.execute(
                    "insert into public.products (uniq_id, product_name, discounted_price) values (%s, %s, %s)",
                    (product, "Demo shirt", price),
                )
                await connection.execute(
                    "insert into public.demo_inventory (product_id, available) values (%s, 10)",
                    (product,),
                )
        try:
            yield pool, [CommerceEngine(pool, user) for user in users], products, users
        finally:
            async with pool.connection() as connection:
                await connection.execute(
                    "delete from public.order_items where order_id in (select id from public.orders where user_id = any(%s))",
                    (users,),
                )
                await connection.execute(
                    "delete from public.orders where user_id = any(%s)", (users,)
                )
                await connection.execute(
                    "delete from public.cart_items where session_id in (select id from public.shopping_sessions where user_id = any(%s))",
                    (users,),
                )
                await connection.execute(
                    "delete from public.shopping_sessions where user_id = any(%s)",
                    (users,),
                )
                await connection.execute(
                    "delete from public.demo_inventory where product_id = any(%s)",
                    (products,),
                )
                await connection.execute(
                    "delete from public.products where uniq_id = any(%s)", (products,)
                )
                await connection.execute(
                    "delete from auth.users where id = any(%s)", (users,)
                )


async def turn(engine):
    message_id = uuid4()
    result = await engine.record_user_message(message_id)
    assert result["status"] == "ok", result
    return message_id, result["state"]["version"]


async def review(engine, product_id, *, delivered=True):
    _, version = await turn(engine)
    added = await engine.add_item(product_id, 1, version)
    assert added["status"] == "ok", added
    message_id, version = await turn(engine)
    address = await engine.set_address(ADDRESS, version)
    prepared = await engine.prepare_order(address["state"]["version"])
    assert prepared["status"] == "ok", prepared
    if delivered:
        assert (
            await engine.record_review_delivery(prepared["pending_token"], uuid4())
        )["status"] == "ok"
    return prepared, message_id


async def approve(engine, prepared):
    message_id, version = await turn(engine)
    return await engine.confirm_order(prepared["pending_token"], version, message_id)


def test_checkout_requires_later_approval_and_retries_return_the_committed_order():
    async def run():
        async with shop() as (pool, engines, products, users):
            engine = engines[0]
            _, version = await turn(engine)
            context = await engine.update_context(
                version,
                add_instruction="Keep answers short",
                language="te",
                result_ids=products,
            )
            assert (await engine.resolve_reference(2, context["state"]["version"]))[
                "product_id"
            ] == products[1]
            prepared, message_id = await review(engine, products[0])
            same_turn = await engine.confirm_order(
                prepared["pending_token"], prepared["state"]["version"], message_id
            )
            assert same_turn["status"] == "later_user_approval_required"
            approved_message, version = await turn(engine)
            confirmed = await engine.confirm_order(
                prepared["pending_token"], version, approved_message
            )
            assert confirmed["status"] == "ok", confirmed
            assert confirmed["order"]["total_paise"] == 10000
            retry = await engine.confirm_order(
                prepared["pending_token"], version, approved_message
            )
            assert retry["order"]["id"] == confirmed["order"]["id"]
            assert retry["already_confirmed"]
            reconnected = (await CommerceEngine(pool, users[0]).get_state())["state"]
            assert reconnected["items"] == []
            assert reconnected["instructions"] == ["Keep answers short"]
            assert reconnected["language"] == "te"
            assert reconnected["result_ids"] == products
            assert reconnected["last_order_id"] == confirmed["order"]["id"]
            async with pool.connection() as connection:
                row = await (
                    await connection.execute(
                        "select available from public.demo_inventory where product_id = %s",
                        (products[0],),
                    )
                ).fetchone()
                assert row["available"] == 9

    asyncio.run(run())


def test_cart_corrections_conflicts_and_interrupted_review_preserve_facts():
    async def run():
        async with shop() as (_, engines, products, _):
            engine = engines[0]
            _, version = await turn(engine)
            added = await engine.add_item(products[0], 2, version)
            corrected = await engine.set_quantity(
                products[0], 1, added["state"]["version"]
            )
            assert corrected["state"]["total_paise"] == 10000
            unchanged = await engine.set_quantity(
                products[0], 1, corrected["state"]["version"]
            )
            assert not unchanged["changed"]
            assert unchanged["state"]["version"] == corrected["state"]["version"]
            assert (await engine.add_item(products[0], 1, version))[
                "status"
            ] == "conflict"
            rejected = await engine.set_quantity(
                products[0], 99, corrected["state"]["version"]
            )
            assert rejected["status"] == "out_of_stock"
            assert rejected["state"]["items"][0]["quantity"] == 1
            address = await engine.set_address(ADDRESS, corrected["state"]["version"])
            changed = await engine.set_address(
                {"line1": "14 Test Road"}, address["state"]["version"]
            )
            assert changed["state"]["address"]["city"] == "Hyderabad"
            prepared = await engine.prepare_order(changed["state"]["version"])
            message_id, version = await turn(engine)
            result = await engine.confirm_order(
                prepared["pending_token"], version, message_id
            )
            assert result["status"] == "stale_token"
            assert not result["state"]["pending_review"]
            prepared = await engine.prepare_order(version)
            await engine.record_review_delivery(prepared["pending_token"], uuid4())
            changed = await engine.set_quantity(products[0], 2, version)
            message_id, version = await turn(engine)
            assert (
                await engine.confirm_order(
                    prepared["pending_token"], version, message_id
                )
            )["status"] == "stale_token"
            assert changed["state"]["items"][0]["quantity"] == 2

    asyncio.run(run())


def test_budget_exception_is_later_scoped_and_does_not_raise_budget():
    async def run():
        async with shop() as (_, engines, products, _):
            engine = engines[0]
            message_id, version = await turn(engine)
            budget = await engine.set_budget(5000, version)
            proposed = await engine.add_item(products[0], 1, budget["state"]["version"])
            assert proposed["status"] == "over_budget"
            assert proposed["state"]["items"] == []
            assert (
                await engine.approve_budget_exception(
                    proposed["exception_token"],
                    proposed["state"]["version"],
                    message_id,
                )
            )["status"] == "later_user_approval_required"
            message_id, version = await turn(engine)
            accepted = await engine.approve_budget_exception(
                proposed["exception_token"], version, message_id
            )
            assert accepted["status"] == "ok", accepted
            assert accepted["state"]["budget_paise"] == 5000
            assert accepted["state"]["total_paise"] == 10000
            version = accepted["state"]["version"]
            again = await engine.add_item(products[1], 1, version)
            assert again["status"] == "over_budget"
            assert len(again["state"]["items"]) == 1
            await engine.set_budget(4000, version)
            message_id, version = await turn(engine)
            assert (
                await engine.approve_budget_exception(
                    again["exception_token"], version, message_id
                )
            )["status"] == "stale_exception"
            address = await engine.set_address(ADDRESS, version)
            proposed = await engine.prepare_order(address["state"]["version"])
            assert proposed["status"] == "over_budget"
            message_id, version = await turn(engine)
            assert (
                await engine.approve_budget_exception(
                    proposed["exception_token"], version, message_id
                )
            )["status"] == "ok"
            assert (await engine.prepare_order(version))["status"] == "ok"

    asyncio.run(run())


def test_checkout_rechecks_price_stock_and_explicit_interruption():
    async def run():
        async with shop() as (pool, engines, products, _):
            engine = engines[0]
            prepared, _ = await review(engine, products[0])
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.products set discounted_price = 110 where uniq_id = %s",
                    (products[0],),
                )
            assert (await approve(engine, prepared))["status"] == "price_changed"
            _, version = await turn(engine)
            prepared = await engine.prepare_order(version)
            await engine.record_review_delivery(prepared["pending_token"], uuid4())
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.demo_inventory set available = 0 where product_id = %s",
                    (products[0],),
                )
            assert (await approve(engine, prepared))["status"] == "out_of_stock"
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.demo_inventory set available = 10 where product_id = %s",
                    (products[0],),
                )
            _, version = await turn(engine)
            prepared = await engine.prepare_order(version)
            await engine.record_review_delivery(prepared["pending_token"], uuid4())
            assert (await engine.interrupt_review(prepared["pending_token"]))[
                "status"
            ] == "ok"
            assert (await approve(engine, prepared))["status"] == "stale_token"
            _, version = await turn(engine)
            prepared = await engine.prepare_order(version)
            await engine.record_review_delivery(prepared["pending_token"], uuid4())
            assert (await approve(engine, prepared))["status"] == "ok"

    asyncio.run(run())


def test_concurrent_edits_conflict_and_competing_checkouts_cannot_oversell():
    async def run():
        async with shop() as (pool, engines, products, users):
            engine = engines[0]
            _, version = await turn(engine)
            results = await asyncio.gather(
                engine.add_item(products[0], 1, version),
                CommerceEngine(pool, users[0]).add_item(products[0], 1, version),
            )
            assert sorted(result["status"] for result in results) == ["conflict", "ok"]
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.demo_inventory set available = 1 where product_id = %s",
                    (products[1],),
                )
            prepared = [(await review(actor, products[1]))[0] for actor in engines]
            approvals = [await turn(actor) for actor in engines]
            results = await asyncio.gather(
                *[
                    actor.confirm_order(pending["pending_token"], version, message_id)
                    for actor, pending, (message_id, version) in zip(
                        engines, prepared, approvals, strict=True
                    )
                ]
            )
            assert sorted(result["status"] for result in results) == [
                "ok",
                "out_of_stock",
            ]
            async with pool.connection() as connection:
                row = await (
                    await connection.execute(
                        "select available from public.demo_inventory where product_id = %s",
                        (products[1],),
                    )
                ).fetchone()
                assert row["available"] == 0

    asyncio.run(run())


def test_failed_commit_rolls_back_order_stock_and_cart_then_allows_retry():
    async def run():
        async with shop() as (_pool, engines, products, _):
            engine = engines[0]
            prepared, _ = await review(engine, products[0])
            message_id, version = await turn(engine)
            with patch(
                "src.engine.orders.save_session",
                side_effect=psycopg.OperationalError("private"),
            ):
                failed = await engine.confirm_order(
                    prepared["pending_token"], version, message_id
                )
            assert failed == {"status": "unavailable"}
            state = (await engine.get_state())["state"]
            assert state["items"][0]["quantity"] == 1
            assert state["items"][0]["available"] == 10
            assert state["last_order_id"] is None
            assert (
                await engine.confirm_order(
                    prepared["pending_token"], version, message_id
                )
            )["status"] == "ok"

    asyncio.run(run())


def test_rls_isolates_shoppers_and_prevents_direct_browser_mutations():
    async def run():
        async with shop() as (pool, engines, products, users):
            prepared, _ = await review(engines[0], products[0])
            assert (await approve(engines[0], prepared))["status"] == "ok"
            _, version = await turn(engines[0])
            assert (await engines[0].add_item(products[1], 1, version))[
                "status"
            ] == "ok"
            await engines[1].get_state()
            async with pool.connection() as connection:
                await connection.execute(
                    "select set_config('request.jwt.claim.sub', %s, true)",
                    (str(users[1]),),
                )
                await connection.execute("set local role authenticated")
                own = await (
                    await connection.execute(
                        "select user_id from public.shopping_sessions"
                    )
                ).fetchall()
                assert [row["user_id"] for row in own] == [users[1]]
                assert (
                    await (
                        await connection.execute("select * from public.cart_items")
                    ).fetchall()
                ) == []
                assert (
                    await (
                        await connection.execute("select * from public.orders")
                    ).fetchall()
                    == []
                )
                assert (
                    await (
                        await connection.execute("select * from public.order_items")
                    ).fetchall()
                    == []
                )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        await connection.execute(
                            "update public.shopping_sessions set version = version + 1"
                        )

    asyncio.run(run())
