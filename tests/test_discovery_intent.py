import asyncio
import json
import os

import pytest
from livekit.agents import APIConnectOptions, llm

from src.agents.shopping_advisor import ShoppingAdvisor
from src.config import Settings
from src.voice.runtime import VoiceRuntime
from src.voice.session import create_voice_session


@pytest.mark.skipif(
    os.environ.get("RUN_DISCOVERY_LIVE") != "1",
    reason="Explicit bounded Cerebras intent check",
)
def test_model_translates_needs_into_catalog_queries():
    async def run():
        agent = ShoppingAdvisor(None)
        tools = [tool for tool in agent.tools if tool.id == "search_products"]
        cases = [
            ("Find me cheap gift ideas.", 50000, None),
            ("Show notebooks between 300 and 700 rupees.", 70000, "range"),
            ("Show the cheapest laptop bags, not laptops.", None, "accessory"),
            (
                "A present for my friend who loves cooking, under 350 rupees.",
                35000,
                "cooking",
            ),
            ("Show me cheap headphones.", None, "headphone"),
            ("ఐదు వందల రూపాయల లోపు బహుమతులు చూపించు.", 50000, None),
        ]
        session = create_voice_session(Settings.load(), VoiceRuntime(None, None))
        async with session.llm:
            for index, (request, ceiling, kind) in enumerate(cases):
                if index:
                    await asyncio.sleep(12)
                context = llm.ChatContext()
                context.add_message(role="system", content=agent.instructions)
                context.add_message(role="user", content=request)
                calls = []
                async with session.llm.chat(
                    chat_ctx=context,
                    tools=tools,
                    conn_options=APIConnectOptions(max_retry=0, timeout=25),
                ) as stream:
                    async for chunk in stream:
                        if chunk.delta:
                            calls.extend(chunk.delta.tool_calls)
                assert len(calls) == 1
                args = json.loads(calls[0].arguments)
                query = args.get("query", "").lower()
                print(request, args)
                assert query and "gift idea" not in query and "cheap" not in query
                assert args.get("max_price_paise") == ceiling
                assert args.get("category", "").lower() not in {
                    "gift",
                    "gifts",
                    "present",
                    "cooking",
                }
                if kind == "range":
                    assert args.get("min_price_paise") == 30000
                    assert "notebook" in query
                elif kind == "accessory":
                    assert "bag" in query
                    assert args.get("sort_by") == "price_asc"
                elif kind == "headphone":
                    assert args.get("sort_by") == "price_asc"
                    assert "headphone" in query
                elif kind == "cooking":
                    assert any(
                        word in query
                        for word in (
                            "kitchen",
                            "cook",
                            "apron",
                            "utensil",
                            "spatula",
                            "pan",
                        )
                    )
                else:
                    assert " or " in query
        await session.stt.aclose()
        await session.tts.aclose()

    asyncio.run(run())


@pytest.mark.skipif(
    os.environ.get("RUN_FILTERS_LIVE") != "1",
    reason="Explicit bounded filter tool check",
)
def test_model_applies_combined_filters_and_sort():
    async def run():
        agent = ShoppingAdvisor(None)
        tools = [tool for tool in agent.tools if tool.id == "search_products"]
        session = create_voice_session(Settings.load(), VoiceRuntime(None, None))
        async with session.llm:
            cases = [
                (
                    "Show blue cotton shirts for women in medium, four stars and up, in stock only, cheapest first.",
                    {"color": "blue", "material": "cotton", "gender": "women"},
                    "available",
                    "price_asc",
                ),
                (
                    "Show Nike shoes that are out of stock, expensive first.",
                    {"brand": "nike"},
                    "out_of_stock",
                    "price_desc",
                ),
            ]
            for index, (request, expected, availability, sort_by) in enumerate(cases):
                if index:
                    await asyncio.sleep(12)
                context = llm.ChatContext()
                context.add_message(role="system", content=agent.instructions)
                context.add_message(role="user", content=request)
                calls = []
                async with session.llm.chat(
                    chat_ctx=context,
                    tools=tools,
                    conn_options=APIConnectOptions(max_retry=0, timeout=25),
                ) as stream:
                    async for chunk in stream:
                        if chunk.delta:
                            calls.extend(chunk.delta.tool_calls)
                assert len(calls) == 1
                args = json.loads(calls[0].arguments)
                print(request, args)
                actual = {k: v.lower() for k, v in args.get("filters", {}).items()}
                assert all(actual.get(k) == value for k, value in expected.items())
                assert args["availability"] == availability
                assert args["sort_by"] == sort_by
                if index == 0:
                    assert actual.get("size") in {"m", "medium"}
                    assert args["min_rating"] == 4
        await session.stt.aclose()
        await session.tts.aclose()

    asyncio.run(run())
