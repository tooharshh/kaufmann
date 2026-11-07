import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from livekit.agents import llm

from src.catalog.search import Catalog
from src.voice.navigation import SELECTION_TOPIC, BrowserBridge, selection_event
from src.voice.runtime import VoiceRuntime
from tests.test_commerce_engine import ADDRESS, shop


def packet(identity, payload, topic=SELECTION_TOPIC):
    return SimpleNamespace(
        topic=topic,
        participant=SimpleNamespace(identity=identity),
        data=json.dumps(payload).encode(),
    )


def test_selection_packets_accept_only_owner_product_selection():
    event = {
        "type": "product_selected",
        "product_id": "shirt",
        "event_id": str(uuid4()),
    }
    assert selection_event(packet("owner", event), "owner") == event
    assert selection_event(packet("other", event), "owner") is None
    assert selection_event(packet("owner", event, topic="lk.chat"), "owner") is None
    for invalid in (
        event | {"type": "confirm_order"},
        event | {"delivered": True},
        event | {"event_id": "fake"},
        event | {"product_id": "x" * 1025},
    ):
        assert selection_event(packet("owner", invalid), "owner") is None


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_product_selection_questions_and_cart_navigation_do_not_fabricate_approval():
    class Finished:
        def __await__(self):
            async def done():
                return self

            return done().__await__()

    async def run():
        async with shop() as (pool, engines, products, _):
            runtime = VoiceRuntime(engines[0], Catalog(pool))
            await runtime.begin_turn(
                llm.ChatMessage(role="user", content=["Show shirts."])
            )
            handle = SimpleNamespace(id="speech", interrupted=False)
            runtime.bind_speech(handle)
            room = SimpleNamespace(
                local_participant=SimpleNamespace(publish_data=AsyncMock()),
                on=Mock(),
                off=Mock(),
            )
            session = SimpleNamespace(
                interrupt=AsyncMock(), generate_reply=Mock(return_value=Finished())
            )
            bridge = BrowserBridge(room, session, runtime, "owner")
            await bridge.start()
            before = (await engines[0].get_state())["state"]
            event = {
                "type": "product_selected",
                "product_id": products[0],
                "event_id": str(uuid4()),
            }
            bridge.receive(packet("owner", event))
            await bridge.task
            state = (await engines[0].get_state())["state"]
            assert state["turn_seq"] == before["turn_seq"]
            assert state["result_ids"] == [products[0]]
            assert state["items"] == []
            assert state["last_order_id"] is None
            assert session.generate_reply.call_args.kwargs["tools"] == []
            assert session.generate_reply.call_args.kwargs["tool_choice"] == "none"
            assert (
                "ask whether they want more details"
                in session.generate_reply.call_args.kwargs["instructions"]
            )
            bridge.receive(packet("owner", event))
            assert session.generate_reply.call_count == 1
            await runtime.present_product(products[0], handle)
            await bridge.navigation_task
            focused = json.loads(room.local_participant.publish_data.call_args.args[0])
            assert focused["type"] == "product" and focused["product_id"] == products[0]
            await runtime.mutate(handle, "add_item", product_id=products[0], quantity=1)
            await bridge.navigation_task
            cart = json.loads(room.local_participant.publish_data.call_args.args[0])
            assert cart["type"] == "cart"
            assert room.local_participant.publish_data.call_args.kwargs[
                "destination_identities"
            ] == ["owner"]
            count = room.local_participant.publish_data.call_count
            assert (
                await runtime.mutate(
                    handle, "add_item", product_id=products[0], quantity=100
                )
            )["status"] == "out_of_stock"
            assert room.local_participant.publish_data.call_count == count
            await runtime.mutate(handle, "set_address", patch=ADDRESS)
            await runtime.mutate(handle, "prepare_order")
            assert runtime.review_token is not None
            await runtime.select_product(products[0])
            assert runtime.review_token is None
            assert not (await engines[0].get_state())["state"]["pending_review"]
            await bridge.close()

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("RUN_VOICE_NAV_LIVE") or not os.environ.get("TEST_DATABASE_URL"),
    reason="Explicit bounded Cerebras navigation check",
)
def test_live_selected_product_gets_a_proactive_details_question():
    from src.agents.concierge import Concierge
    from src.config import Settings
    from src.voice.session import create_voice_session

    async def run():
        async with shop() as (pool, engines, products, _):
            runtime = VoiceRuntime(engines[0], Catalog(pool))
            async with create_voice_session(Settings.load(), runtime) as session:
                await session.start(Concierge(runtime))
                bridge = BrowserBridge(SimpleNamespace(), session, runtime, "owner")
                async with asyncio.timeout(35):
                    await bridge.select(products[0])
                replies = [
                    item.text_content
                    for item in session.history.items
                    if isinstance(item, llm.ChatMessage) and item.role == "assistant"
                ]
                assert replies and "?" in replies[-1]
                print("Proactive question:", replies[-1])
                state = (await engines[0].get_state())["state"]
                assert state["items"] == []
                assert state["turn_seq"] == 0
                assert state["last_order_id"] is None

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("RUN_NAV_TRANSPORT_LIVE")
    or not os.environ.get("TEST_DATABASE_URL"),
    reason="Explicit ephemeral LiveKit transport check",
)
def test_live_room_delivers_product_selection_and_agent_navigation():
    from datetime import timedelta

    from livekit import api, rtc

    from src.config import Settings

    class Finished:
        def __await__(self):
            async def done():
                return self

            return done().__await__()

    async def run():
        settings = Settings.load()
        room_name = "kaufmann-navigation-check-" + uuid4().hex
        identity = "navigation-check-shopper"

        def token(participant, agent=False):
            return (
                api.AccessToken(
                    settings["LIVEKIT_API_KEY"], settings["LIVEKIT_API_SECRET"]
                )
                .with_identity(participant)
                .with_kind("agent" if agent else "standard")
                .with_ttl(timedelta(minutes=2))
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=room_name,
                        agent=agent,
                        can_publish=False,
                        can_publish_data=True,
                    )
                )
                .with_room_config(
                    api.RoomConfiguration(
                        empty_timeout=10, departure_timeout=5, max_participants=2
                    )
                )
                .to_jwt()
            )

        async with shop() as (pool, engines, products, _):
            agent_room = rtc.Room()
            shopper_room = rtc.Room()
            runtime = VoiceRuntime(engines[0], Catalog(pool))
            session = SimpleNamespace(
                interrupt=AsyncMock(), generate_reply=Mock(return_value=Finished())
            )
            bridge = BrowserBridge(agent_room, session, runtime, identity)
            received = []
            changed = asyncio.Event()

            @shopper_room.on("data_received")
            def received_data(packet):
                if packet.topic == "kaufmann.navigation":
                    assert (
                        packet.participant.kind
                        == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
                    )
                    received.append(json.loads(packet.data))
                    changed.set()

            try:
                async with asyncio.timeout(25):
                    await shopper_room.connect(settings["LIVEKIT_URL"], token(identity))
                    await agent_room.connect(
                        settings["LIVEKIT_URL"], token("navigation-check-agent", True)
                    )
                    await bridge.start()
                    await changed.wait()
                    await shopper_room.local_participant.publish_data(
                        json.dumps(
                            {
                                "type": "product_selected",
                                "product_id": products[0],
                                "event_id": str(uuid4()),
                            }
                        ),
                        topic=SELECTION_TOPIC,
                        reliable=True,
                    )
                    while bridge.task is None:
                        await asyncio.sleep(0.02)
                    await bridge.task
                    assert session.generate_reply.call_count == 1
                    await runtime.present_product(products[0])
                    while not any(event["type"] == "product" for event in received):
                        changed.clear()
                        await changed.wait()
                    await runtime.begin_turn(
                        llm.ChatMessage(role="user", content=["Add one shirt."])
                    )
                    handle = SimpleNamespace(
                        id="live-transport-turn", interrupted=False
                    )
                    runtime.bind_speech(handle)
                    result = await runtime.mutate(
                        handle, "add_item", product_id=products[0], quantity=1
                    )
                    assert result["status"] == "ok"
                    while not any(event["type"] == "cart" for event in received):
                        changed.clear()
                        await changed.wait()
                    print(
                        "LiveKit delivered selection, product navigation and cart navigation"
                    )
            finally:
                await bridge.close()
                await agent_room.disconnect()
                await shopper_room.disconnect()

    asyncio.run(run())
