import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from src.catalog.search import Catalog
from src.catalog.selection import catalog_options, select_catalog
from src.catalog.versioned_import import import_version, validate_catalog
from src.engine.cart import CommerceEngine
from src.state.memory import PreferenceMemory
from src.state.session import Refusal
from tests.test_commerce_engine import ADDRESS, shop, turn


def fixture_catalog(tmp_path: Path, stock=3):
    source = tmp_path / "equipment.json"
    source.write_text(
        json.dumps(
            [
                {
                    "sku": "one",
                    "title": "Field telescope",
                    "cost": "249.50",
                    "inventory": stock,
                    "specs": {"aperture": "70 mm"},
                }
            ]
        )
    )
    return validate_catalog(
        source,
        {
            "fields": {
                "id": "sku",
                "name": "title",
                "price": "cost",
                "stock": "inventory",
                "attributes": "specs",
            },
            "price_unit": "rupees",
            "currency": "INR",
        },
    )


def test_catalog_import_requires_units_currency_and_valid_stock(tmp_path):
    products, rejected, _ = fixture_catalog(tmp_path, None)
    assert not rejected
    assert products[0]["stock"] is None
    assert products[0]["stock_basis"] == "unknown"
    assert products[0]["price_paise"] == 24950
    _, rejected, _ = fixture_catalog(tmp_path, -1)
    assert rejected[0]["reason"] == "invalid_stock"
    with pytest.raises(ValueError):
        validate_catalog(
            tmp_path / "equipment.json",
            {
                "fields": {"id": "sku", "name": "title", "price": "cost"},
                "price_unit": "paise",
            },
        )


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_delivery_proposal_requires_delivery_later_approval_and_preserves_fields():
    async def run():
        async with shop() as (_, engines, products, _):
            engine = engines[0]
            _, version = await turn(engine)
            state = await engine.set_address(ADDRESS, version)
            proposal = await engine.propose_address(
                {"line1": "24 Changed Road"}, state["state"]["version"]
            )
            token = proposal["proposal_token"]
            assert proposal["state"]["address"] == ADDRESS
            assert (
                await engine.approve_address(
                    token, proposal["state"]["version"], uuid4()
                )
            )["status"] == "proposal_not_delivered"
            assert (await engine.record_address_delivery(token))["status"] == "ok"
            assert (
                await engine.approve_address(
                    token, proposal["state"]["version"], engines[0].user_id
                )
            )["status"] == "later_user_approval_required"
            message, version = await turn(engine)
            approved = await engine.approve_address(token, version, message)
            assert approved["status"] == "ok"
            assert approved["state"]["address"] == {
                **ADDRESS,
                "line1": "24 Changed Road",
            }
            proposal = await engine.propose_address(
                {"city": "Other"}, approved["state"]["version"]
            )
            await engine.cancel_address(proposal["state"]["version"])
            assert (await engine.get_state())["state"]["address"]["city"] == ADDRESS[
                "city"
            ]
            proposal = await engine.propose_address(
                {"city": "Other"}, proposal["state"]["version"]
            )
            changed = await engine.add_item(
                products[0], 1, proposal["state"]["version"]
            )
            assert not changed["state"]["pending_address"]
            assert (await engine.record_address_delivery(proposal["proposal_token"]))[
                "status"
            ] == "stale_proposal"

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_catalog_access_cart_isolation_immutable_versions_and_pinned_voice(tmp_path):
    async def run():
        async with shop() as (pool, engines, products, users):
            accepted, rejected, report = fixture_catalog(tmp_path)
            async with pool.connection() as connection:
                catalog_id = await import_version(
                    connection, "Held-out equipment", accepted, rejected, report
                )
                await connection.execute(
                    "insert into public.catalog_grants(user_id,catalog_id) values (%s,%s)",
                    (users[0], catalog_id),
                )
            assert len((await catalog_options(pool, users[1]))["catalogs"]) == 1
            with pytest.raises(Refusal):
                await select_catalog(pool, users[1], catalog_id)
            await select_catalog(pool, users[0], catalog_id)
            selection = await catalog_options(pool, users[0])
            pinned = CommerceEngine(pool, users[0], catalog_id, selection["generation"])
            catalog = Catalog(pool, catalog_id, users[0], selection["generation"])
            found = await catalog.search("telescope", filters={"aperture": "70 mm"})
            assert found["status"] == "ok", found
            product = found["products"][0]
            assert product["source_product_id"] == "one"
            assert product["stock_basis"] == "source"
            _, version = await turn(pinned)
            assert (await pinned.add_item(products[0], 1, version))[
                "status"
            ] == "not_found"
            assert (await pinned.add_item(product["id"], 1, version))["status"] == "ok"
            default = (await catalog_options(pool, users[1]))["catalog_id"]
            await select_catalog(pool, users[0], default)
            assert (await pinned.get_state())["status"] == "catalog_changed"
            assert (await engines[0].get_state())["state"]["items"] == []
            await select_catalog(pool, users[0], catalog_id)
            assert (await pinned.get_state())["status"] == "catalog_changed"
            assert (await engines[0].get_state())["state"]["items"][0][
                "product_id"
            ] == product["id"]

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_memory_ownership_supersession_forget_and_queued_extraction_epoch():
    async def run():
        async with shop() as (pool, _, _, users):
            memory = PreferenceMemory(pool, users[0])
            other = PreferenceMemory(pool, users[1])
            fact = {
                "subject": "self",
                "scope": "clothing",
                "key": "size",
                "value": "medium",
            }
            assert (await memory.change("remember", fact, uuid4()))["status"] == "ok"
            assert (await other.inspect())["facts"] == []
            old = (await memory.inspect())["revision"]
            await memory.change("remember", {**fact, "value": "large"}, uuid4())
            assert (await memory.relevant("clothing"))["facts"][0]["value"] == "large"
            await memory.change("forget", fact, uuid4())
            assert (
                await memory.change("remember", fact, uuid4(), expected_revision=old)
            )["status"] == "conflict"
            assert (await memory.inspect())["facts"] == []

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_discovery_reconnect_preserves_constraints_and_expiration_clears_runtime():
    from types import SimpleNamespace

    from src.voice.runtime import VoiceRuntime

    async def run():
        async with shop() as (pool, engines, products, _):
            engine = engines[0]
            message, version = await turn(engine)
            task = {
                "constraints": {
                    "budget_paise": 50000,
                    "recipient": "brother",
                    "exclusions": ["jewellery"],
                },
                "original_input": "Gift kavali",
                "selected_product_id": products[0],
                "rejected_ids": [products[1]],
                "search_arguments": {
                    "query": "shirt",
                    "max_price_paise": 50000,
                    "limit": 1,
                    "offset": 0,
                },
            }
            await engine.update_context(
                version, result_ids=[products[0]], shopping_task=task
            )
            runtime = VoiceRuntime(engine, Catalog(pool))
            await runtime.refresh()
            assert runtime.focused_product["id"] == products[0]
            assert runtime.last_search_arguments["max_price_paise"] == 50000
            runtime.message_id = message
            handle = SimpleNamespace(id="new-speech", interrupted=False)
            runtime.bind_speech(handle)
            result = await runtime.search_more(handle)
            assert (
                result["state"]["shopping_task"]["constraints"] == task["constraints"]
            )
            assert products[1] not in [p["id"] for p in result["products"]]
            async with pool.connection() as connection:
                await connection.execute(
                    "update public.shopping_sessions set task_updated_at = now() - interval '8 days' where id = %s",
                    (result["state"]["session_id"],),
                )
            await runtime.refresh()
            assert runtime.last_search_arguments is None
            assert runtime.state["result_ids"] == []

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_import_immutability_unknown_inventory_and_database_read_policies(tmp_path):
    import psycopg

    async def run():
        async with shop() as (pool, engines, _, users):
            accepted, rejected, report = fixture_catalog(tmp_path, stock=None)
            async with pool.connection() as connection:
                catalog_id = await import_version(
                    connection, "Unknown inventory", accepted, rejected, report
                )
                await connection.execute(
                    "insert into public.catalog_grants(user_id,catalog_id) values (%s,%s)",
                    (users[0], catalog_id),
                )
            await select_catalog(pool, users[0], catalog_id)
            product = (await Catalog(pool, catalog_id).search("telescope"))["products"][
                0
            ]
            message, version = await turn(engines[0])
            assert (await engines[0].add_item(product["id"], 1, version))[
                "status"
            ] == "inventory_unknown"
            memory = PreferenceMemory(pool, users[0])
            await memory.change(
                "remember",
                {
                    "subject": "self",
                    "scope": "clothing",
                    "key": "size",
                    "value": "medium",
                },
                message,
            )
            async with pool.connection() as connection:
                with pytest.raises(psycopg.errors.RaiseException):
                    async with connection.transaction():
                        await connection.execute(
                            "update public.products set product_name = 'Changed' where uniq_id = %s",
                            (product["id"],),
                        )
            for user, expected in ((users[0], 1), (users[1], 0)):
                async with pool.connection() as connection, connection.transaction():
                    await connection.execute("set local role authenticated")
                    await connection.execute(
                        "select set_config('request.jwt.claim.sub', %s, true)",
                        (str(user),),
                    )
                    rows = await (
                        await connection.execute(
                            "select uniq_id from public.products where catalog_id = %s",
                            (catalog_id,),
                        )
                    ).fetchall()
                    assert len(rows) == expected
                    rows = await (
                        await connection.execute(
                            "select value from public.preference_memory where user_id = %s",
                            (users[0],),
                        )
                    ).fetchall()
                    assert len(rows) == expected

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_recipient_memory_does_not_apply_shopper_size_to_a_gift():
    async def run():
        async with shop() as (pool, _, _, users):
            memory = PreferenceMemory(pool, users[0])
            await memory.change(
                "remember",
                {
                    "subject": "self",
                    "scope": "clothing",
                    "key": "size",
                    "value": "medium",
                },
                uuid4(),
            )
            await memory.change(
                "remember",
                {
                    "subject": "recipient:brother",
                    "scope": "clothing",
                    "key": "size",
                    "value": "large",
                },
                uuid4(),
            )
            own = await memory.relevant("Show shirts for myself")
            assert [f["value"] for f in own["facts"]] == ["medium"]
            gift = await memory.relevant("Show shirts", recipient="brother")
            assert [f["value"] for f in gift["facts"]] == ["large"]
            unknown = await memory.relevant("Show shirts", recipient="friend")
            assert unknown["facts"] == []

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_automatic_memory_survives_new_runtime_and_retains_only_stable_source_facts():
    from types import SimpleNamespace

    from src.state.memory import MemoryQueue
    from src.voice.runtime import VoiceRuntime

    async def run():
        async with shop() as (pool, engines, _, users):
            memory = PreferenceMemory(pool, users[0])
            statement = "I usually wear medium."

            async def extract(text):
                return [
                    {
                        "stable": text == statement,
                        "evidence": text,
                        "fact": {
                            "subject": "self",
                            "scope": "clothing",
                            "key": "size",
                            "value": "M",
                        },
                    }
                ]

            queue = MemoryQueue(memory, extract)
            source, _ = await turn(engines[0])
            queue.submit(statement, source, 0)
            async with asyncio.timeout(3):
                await queue.queue.join()
            facts = (await memory.inspect())["facts"]
            assert len(facts) == 1 and facts[0]["value"] == "medium"
            assert statement not in json.dumps(facts)
            revision = (await memory.inspect())["revision"]
            queue.submit("Add a medium shirt just for today.", uuid4(), revision)
            async with asyncio.timeout(3):
                await queue.queue.join()
            assert (await memory.inspect())["revision"] == revision
            await queue.close()
            returning = VoiceRuntime(CommerceEngine(pool, users[0]), Catalog(pool))
            returning.memory = PreferenceMemory(pool, users[0])
            await returning.begin_turn(
                SimpleNamespace(
                    id=str(uuid4()), text_content="Naa kosam shirts chupinchu."
                )
            )
            assert returning.memory_facts[0]["value"] == "medium"
            await returning.memory.change(
                "remember",
                {
                    "subject": "self",
                    "scope": "clothing",
                    "key": "size",
                    "value": "large",
                },
                uuid4(),
            )
            await returning.refresh_memory()
            assert [f["value"] for f in returning.memory_facts] == ["large"]
            await returning.memory.change(
                "forget",
                {
                    "subject": "self",
                    "scope": "clothing",
                    "key": "size",
                    "value": "large",
                },
                uuid4(),
            )
            another = PreferenceMemory(pool, users[0])
            assert (await another.inspect())["facts"] == []

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_forget_wrong_scope_never_claims_a_fact_was_deleted():
    async def run():
        async with shop() as (pool, _, _, users):
            memory = PreferenceMemory(pool, users[0])
            fact = {
                "subject": "self",
                "scope": "clothing",
                "key": "size",
                "value": "medium",
            }
            await memory.change("remember", fact, uuid4())
            result = await memory.change(
                "forget", {**fact, "scope": "general"}, uuid4()
            )
            assert result["status"] == "scope_required" and result["changed"] is False
            assert result["matching_scopes"] == ["clothing"]
            assert len((await PreferenceMemory(pool, users[0]).inspect())["facts"]) == 1
            assert (await memory.change("forget", fact, uuid4()))["changed"] is True
            assert (await PreferenceMemory(pool, users[0]).inspect())["facts"] == []

    asyncio.run(run())
