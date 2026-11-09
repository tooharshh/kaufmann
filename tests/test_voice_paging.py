import asyncio
from types import SimpleNamespace
from uuid import uuid4

from src.voice.runtime import VoiceRuntime


def test_repeated_catalog_search_advances_and_show_more_keeps_constraints():
    class Engine:
        async def update_context(self, version, result_ids, shopping_task):
            return {
                "status": "ok",
                "state": {
                    "version": version + 1,
                    "shopping_task": shopping_task,
                    "result_ids": result_ids,
                    "pending_budget_exception": False,
                    "pending_review": False,
                    "items": [],
                },
            }

    class Catalog:
        def __init__(self):
            self.calls = []

        async def search(self, **arguments):
            self.calls.append(arguments)
            offset = arguments["offset"]
            return {
                "status": "ok",
                "products": [{"id": f"product-{offset + index}"} for index in range(3)],
                "has_more": True,
                "offset": offset,
            }

    async def run():
        catalog = Catalog()
        runtime = VoiceRuntime(Engine(), catalog)
        navigation = []

        async def publish(event):
            navigation.append(event)
            return "queued"

        runtime.publish_navigation = publish
        runtime.state = {
            "version": 0,
            "result_ids": [],
            "pending_budget_exception": False,
            "pending_review": False,
            "items": [],
        }
        handle = SimpleNamespace(id="speech", interrupted=False)
        runtime.message_id = uuid4()
        runtime.bind_speech(handle)
        arguments = {
            "query": "mug OR notebook",
            "filters": {"gender": "men"},
            "limit": 3,
            "offset": 0,
        }
        await runtime.search(handle, **arguments)
        await runtime.search_more(handle)
        await runtime.search(handle, **arguments)
        assert [call["offset"] for call in catalog.calls] == [0, 3, 6]
        assert catalog.calls[1]["filters"] == {"gender": "men"}
        assert navigation[1]["offset"] == 3
        assert navigation[1]["focus_product_id"] == "product-3"

    asyncio.run(run())


def test_closest_search_marks_relaxed_preference_and_keeps_budget():
    class Engine:
        async def update_context(self, version, result_ids, shopping_task):
            return {
                "status": "ok",
                "state": {
                    "version": version + 1,
                    "shopping_task": shopping_task,
                    "result_ids": result_ids,
                    "pending_budget_exception": False,
                    "pending_review": False,
                    "items": [],
                },
            }

    class Catalog:
        async def search(self, **arguments):
            assert arguments["max_price_paise"] == 50000
            assert arguments["filters"] == {}
            return {
                "status": "ok",
                "products": [{"id": "alternative-1", "name": "A different color"}],
                "has_more": False,
                "offset": 0,
            }

    async def run():
        runtime = VoiceRuntime(Engine(), Catalog())
        runtime.state = {
            "version": 0,
            "result_ids": [],
            "pending_budget_exception": False,
            "pending_review": False,
            "items": [],
        }
        handle = SimpleNamespace(id="speech", interrupted=False)
        runtime.message_id = uuid4()
        runtime.bind_speech(handle)
        result = await runtime.search_closest(
            handle,
            query="mug",
            max_price_paise=50000,
            filters={"color": "blue"},
            relax_fields=["color"],
        )
        assert result["status"] == "alternatives"
        assert result["exact_match"] is False
        assert result["relaxed_filters"] == {"color": "blue"}

    asyncio.run(run())
