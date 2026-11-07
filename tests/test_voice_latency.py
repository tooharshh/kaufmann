import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

from livekit.agents import Agent, llm

from src.agents.base import StoreAgent
from src.voice.latency import observe_latency
from src.voice.runtime import VoiceRuntime


def test_tool_steps_reuse_state_but_new_user_turn_reloads():
    async def run():
        state = {
            "version": 1,
            "pending_review": False,
            "pending_budget_exception": False,
        }
        changed = {**state, "version": 2}
        engine = SimpleNamespace(
            record_user_message=AsyncMock(
                side_effect=[
                    {"status": "ok", "state": state},
                    {"status": "ok", "state": changed},
                    {"status": "unavailable"},
                ]
            ),
            get_state=AsyncMock(),
        )
        runtime = VoiceRuntime(engine, None)
        first = llm.ChatMessage(role="user", content=["Find shoes."])
        await runtime.begin_turn(first)
        await runtime.begin_turn(first)
        assert engine.record_user_message.await_count == 1
        assert engine.get_state.await_count == 0
        second = llm.ChatMessage(role="user", content=["What changed in my basket?"])
        result = await runtime.begin_turn(second)
        assert result["state"]["version"] == 2
        assert engine.record_user_message.await_count == 2
        handle = SimpleNamespace(id="second", interrupted=False)
        runtime.bind_speech(handle)
        failed = await runtime.begin_turn(
            llm.ChatMessage(role="user", content=["Confirm it."])
        )
        assert failed["status"] == "unavailable"
        assert runtime.state is None
        assert not runtime.allowed(handle)

    asyncio.run(run())


def test_speech_receives_first_word_without_waiting_for_long_prefix():
    async def run():
        waiting = asyncio.Event()

        async def text():
            yield "Hello"
            await waiting.wait()
            yield " there."

        async def synthesize(agent, source, model_settings):
            async for chunk in source:
                yield chunk

        tts = SimpleNamespace(update_options=lambda **kwargs: None)
        with (
            patch.object(
                StoreAgent,
                "session",
                new_callable=PropertyMock,
                return_value=SimpleNamespace(tts=tts, current_speech=None),
            ),
            patch.object(Agent.default, "tts_node", synthesize),
        ):
            stream = StoreAgent(None, "").tts_node(text(), None)
            async with asyncio.timeout(0.5):
                assert await anext(stream) == "Hello"
            await stream.aclose()

    asyncio.run(run())


def test_latency_logs_only_timing_fields(caplog):
    message = llm.ChatMessage(
        role="assistant",
        content=["Private delivery address"],
        metrics={"llm_node_ttft": 0.15, "e2e_latency": 0.8},
    )
    with caplog.at_level("INFO", logger="kaufmann.voice.latency"):
        observe_latency(SimpleNamespace(item=message))
    assert '"e2e_latency_ms": 800' in caplog.text
    assert "Private delivery address" not in caplog.text


def test_filter_cache_coalesces_loads_and_does_not_cache_failures():
    from src.catalog.search import Catalog

    async def run():
        catalog = Catalog(None)
        catalog._fetch = AsyncMock(side_effect=[None, [], []])
        assert (await catalog.filter_options())["status"] == "unavailable"
        results = await asyncio.gather(*(catalog.filter_options() for _ in range(5)))
        assert catalog._fetch.await_count == 2
        results[0]["categories"].append("corrupted")
        assert (await catalog.filter_options())["categories"] == []
        catalog._filter_expires = 0
        await catalog.filter_options()
        assert catalog._fetch.await_count == 3

    asyncio.run(run())


def test_navigation_does_not_block_and_coalesces_pending_updates():
    from unittest.mock import Mock

    from src.voice.navigation import BrowserBridge

    async def run():
        blocked = asyncio.Event()
        sent = []

        async def publish(data, **kwargs):
            import json

            sent.append(json.loads(data)["type"])
            await blocked.wait()

        room = SimpleNamespace(
            local_participant=SimpleNamespace(publish_data=publish), off=Mock()
        )
        bridge = BrowserBridge(room, None, SimpleNamespace(message_id=None), "owner")
        assert await bridge.publish({"type": "product"}) == "queued"
        await asyncio.sleep(0)
        await bridge.publish({"type": "catalog"})
        await bridge.publish({"type": "cart"})
        assert sent == ["product"]
        blocked.set()
        await bridge.navigation_task
        assert sent == ["product", "cart"]
        await bridge.close()
        assert await bridge.publish({"type": "cart"}) == "unavailable"

    asyncio.run(run())
