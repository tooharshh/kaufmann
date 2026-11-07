import asyncio
import json
import os
from collections import deque
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from livekit.agents import AgentSession, llm

from src.agents.concierge import Concierge
from src.catalog.search import Catalog
from src.config import Settings
from src.voice.access import (
    dispatch_metadata,
    verify_dispatch,
    verify_dispatch_context,
    voice_session,
)
from src.voice.runtime import VoiceRuntime
from tests.test_commerce_engine import ADDRESS, shop


def test_voice_tokens_bind_verified_owner_room_and_expiry():
    user = uuid4()
    settings = Settings(
        {
            "LIVEKIT_URL": "wss://example.livekit.cloud",
            "LIVEKIT_API_KEY": "local-test-key",
            "LIVEKIT_API_SECRET": "local-test-secret-with-at-least-32-bytes",
            "VOICE_DISPATCH_SECRET": "different-shared-dispatch-secret-32-bytes",
        }
    )
    result = voice_session(settings, user, "sample-user-access-token")
    decoded = jwt.decode(
        result["token"],
        settings["LIVEKIT_API_SECRET"],
        algorithms=["HS256"],
        issuer=settings["LIVEKIT_API_KEY"],
    )
    assert decoded["sub"] == "shopper:" + str(user)
    assert decoded["video"]["room"] == result["room"]
    assert decoded["video"]["canPublishSources"] == ["microphone"]
    assert not decoded["video"].get("roomAdmin")
    dispatch = decoded["roomConfig"]["agents"][0]
    assert dispatch["agentName"] == "kaufmann-shopping"
    assert (
        verify_dispatch(
            dispatch["metadata"], result["room"], settings["VOICE_DISPATCH_SECRET"]
        )
        == user
    )
    assert (
        verify_dispatch_context(
            dispatch["metadata"], result["room"], settings["VOICE_DISPATCH_SECRET"]
        )["access_token"]
        == "sample-user-access-token"
    )
    metadata = dispatch_metadata(
        user, "room", settings["VOICE_DISPATCH_SECRET"], now=1000
    )
    for envelope, room, now in [
        (metadata, "other", 1001),
        (metadata, "room", 1600),
        (metadata.replace("payload", "tampered"), "room", 1001),
    ]:
        with pytest.raises(ValueError):
            verify_dispatch(envelope, room, settings["VOICE_DISPATCH_SECRET"], now=now)


class ScriptedLLM(llm.LLM):
    def __init__(self):
        super().__init__()
        self.steps = deque()
        self.contexts = []

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs):
        self.contexts.append(chat_ctx.copy())
        assert self.steps, "Unexpected model request"
        return ScriptedStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )


class ScriptedStream(llm.LLMStream):
    async def _run(self):
        step = self._llm.steps.popleft()
        if isinstance(step, str):
            delta = llm.ChoiceDelta(role="assistant", content=step)
        else:
            name, arguments = step
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name=name, arguments=json.dumps(arguments), call_id=uuid4().hex
                    )
                ],
            )
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid4().hex, delta=delta))


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_sdk_turns_handoffs_and_tools_use_persisted_state():
    async def run():
        async with shop() as (pool, engines, products, _):
            runtime = VoiceRuntime(engines[0], Catalog(pool))
            model = ScriptedLLM()
            async with AgentSession(
                llm=model, vad=None, turn_detection=None, max_tool_steps=6
            ) as session:
                await session.start(Concierge(runtime))
                model.steps.extend(
                    [
                        ("focus_shopping", {"phase": "basket"}),
                        ("save_preference", {"add_instruction": "keep replies brief"}),
                        ("set_budget", {"budget_paise": 50000}),
                        "Your budget is saved.",
                    ]
                )
                async with asyncio.timeout(10):
                    await session.run(
                        user_input="Keep replies brief and set a five hundred rupee budget."
                    )
                state = (await engines[0].get_state())["state"]
                assert state["budget_paise"] == 50000
                assert state["instructions"] == ["keep replies brief"]
                assert state["turn_seq"] == 1
                model.steps.extend(
                    [("add_item", {"product_id": products[0], "quantity": 2}), "Added."]
                )
                await session.run(user_input="Add two shirts.")
                assert (await engines[0].get_state())["state"]["items"][0][
                    "quantity"
                ] == 2
                model.steps.extend(
                    [
                        ("set_quantity", {"product_id": products[0], "quantity": 1}),
                        "One shirt.",
                    ]
                )
                await session.run(user_input="Actually make it one.")
                state = (await engines[0].get_state())["state"]
                assert state["items"][0]["quantity"] == 1
                await engines[0].set_budget(25000, state["version"])
                model.steps.extend(
                    [
                        ("focus_shopping", {"phase": "checkout"}),
                        (
                            "set_address",
                            {
                                key: value
                                for key, value in ADDRESS.items()
                                if key != "country"
                            },
                        ),
                        "Address saved.",
                    ]
                )
                await session.run(user_input="Deliver to my Hyderabad address.")
                state = (await engines[0].get_state())["state"]
                assert state["budget_paise"] == 25000
                assert state["address"] == ADDRESS
                assert state["turn_seq"] == 4
                assert state["instructions"] == ["keep replies brief"]
                assert model.steps == deque()
                fresh = model.contexts[-1].items[-1].text_content
                assert '"budget_paise": 25000' in fresh
                model.steps.extend(
                    [("review_order", {}), "Please use the browser to review."]
                )
                await session.run(user_input="Let's order.")
                assert (await engines[0].get_state())["state"][
                    "pending_review"
                ] is False
                model.steps.extend([("confirm_order", {}), "We need a review first."])
                await session.run(user_input="Yes.")
                assert (await engines[0].get_state())["state"]["last_order_id"] is None

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_voice_review_delivery_rejects_interruption_and_requires_later_turn():
    async def run():
        async with shop() as (pool, engines, products, _):
            engine = engines[0]
            runtime = VoiceRuntime(engine, Catalog(pool))
            await runtime.begin_turn(
                llm.ChatMessage(role="user", content=["Order one shirt."])
            )
            handle = SimpleNamespace(id="first", interrupted=False)
            runtime.bind_speech(handle)
            await runtime.mutate(handle, "add_item", product_id=products[0], quantity=1)
            await runtime.mutate(handle, "set_address", patch=ADDRESS)
            prepared = await runtime.mutate(handle, "prepare_order")

            class Delivery:
                interrupted = True

                def __init__(self):
                    self.chat_items = [
                        llm.ChatMessage(
                            role="assistant", content=["Review interrupted."]
                        )
                    ]

                async def wait_for_playout(self):
                    pass

                def exception(self):
                    return None

            await runtime.deliver_review(prepared["pending_token"], Delivery())
            assert (await engine.get_state())["state"]["pending_review"] is False
            prepared = await runtime.mutate(handle, "prepare_order")
            speech = Delivery()
            speech.interrupted = False
            assert (await runtime.deliver_review(prepared["pending_token"], speech))[
                "status"
            ] == "ok"
            assert (await runtime.mutate(handle, "confirm_order"))[
                "status"
            ] == "later_user_approval_required"
            await runtime.begin_turn(
                llm.ChatMessage(role="user", content=["Go ahead."])
            )
            assert (await runtime.mutate(handle, "confirm_order"))[
                "status"
            ] == "user_turn_required"
            later = SimpleNamespace(id="later", interrupted=False)
            runtime.bind_speech(later)
            confirmed = await runtime.mutate(later, "confirm_order")
            assert confirmed["status"] == "ok"
            assert confirmed["order"]["total_paise"] == 10000

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("RUN_VOICE_LIVE") or not os.environ.get("TEST_DATABASE_URL"),
    reason="Explicit local provider smoke only",
)
def test_live_provider_understands_quantity_correction():
    from src.agents.cart import CartAgent
    from src.voice.session import create_voice_session

    async def run():
        async with shop() as (pool, engines, products, _):
            await engines[0].add_item(products[0], 1, 0)
            runtime = VoiceRuntime(engines[0], Catalog(pool))
            session = create_voice_session(Settings.load(), runtime)
            async with session:
                await session.start(CartAgent(runtime))
                async with asyncio.timeout(40):
                    await session.run(
                        user_input="Actually, make that two instead of one, please."
                    )
                state = (await engines[0].get_state())["state"]
                assert len(state["items"]) == 1
                assert state["items"][0]["quantity"] == 2
                assert state["total_paise"] == 20000
                assert state["last_order_id"] is None

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("RUN_ADDRESS_LIVE") or not os.environ.get("TEST_DATABASE_URL"),
    reason="Bounded live address correction",
)
def test_live_single_address_field_edit_preserves_existing_details():
    from src.agents.checkout import CheckoutAgent
    from src.voice.session import create_voice_session

    async def run():
        async with shop() as (pool, engines, _products, _users):
            current = (await engines[0].get_state())["state"]
            await engines[0].set_address(ADDRESS, current["version"])
            runtime = VoiceRuntime(engines[0], Catalog(pool))
            async with create_voice_session(Settings.load(), runtime) as session:
                await session.start(CheckoutAgent(runtime))
                async with asyncio.timeout(40):
                    await session.run(
                        user_input="Change only my state to Karnataka. Keep all my other delivery details the same."
                    )
                state = (await engines[0].get_state())["state"]
                assert state["address"] == {**ADDRESS, "state": "Karnataka"}
                assert state["last_order_id"] is None
                replies = [
                    item.text_content
                    for item in session.history.items
                    if isinstance(item, llm.ChatMessage) and item.role == "assistant"
                ]
                print("Address response:", replies[-1])
                assert "?" not in replies[-1]

    asyncio.run(run())
