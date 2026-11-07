import asyncio
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.catalog.search import Catalog
from src.voice.latency import timed
from src.voice.presentation import voice_result


class VoiceRuntime:
    def __init__(self, engine, catalog: Catalog, profile_auth=None, access_token=None):
        self.engine = engine
        self.catalog = catalog
        self.lock = asyncio.Lock()
        self.state = None
        self.message_id = None
        self.request = ""
        self.budget_token = None
        self.review_token = None
        self.review_version = None
        self.speech_turns = {}
        self.publish_navigation = None
        self.focused_product = None
        self.speech_names = []
        self.last_search_signature = None
        self.last_search_offset = 0
        self.last_search_arguments = None
        self.profile_auth = profile_auth
        self.profile_authorization = "Bearer " + access_token if access_token else None
        self.profile_owner = getattr(engine, "user_id", None)

    async def profile(self):
        if not self.profile_auth or not self.profile_authorization:
            return {"status": "unavailable"}
        from src.profile import profile_view, user_request

        try:
            user = await user_request(
                self.profile_auth, self.profile_authorization, self.profile_owner
            )
        except (ValueError, TypeError, KeyError, TimeoutError):
            return {"status": "unavailable"}
        return {"status": "ok", "profile": profile_view(user)}

    async def update_profile(self, operation, data):
        current = await self.profile()
        if current["status"] != "ok":
            return current
        from src.profile import update_profile

        try:
            return await update_profile(
                self.profile_auth,
                self.profile_authorization,
                self.profile_owner,
                operation,
                data,
                current["profile"]["revision"],
            )
        except (ValueError, TypeError, KeyError, TimeoutError):
            return {"status": "unavailable"}

    def remember(self, result):
        if "state" in result:
            self.state = result["state"]
        if result.get("exception_token"):
            self.budget_token = result["exception_token"]
        if self.state and not self.state["pending_budget_exception"]:
            self.budget_token = None
        if self.state and not self.state["pending_review"]:
            self.review_token = None
        return result

    @timed("runtime.begin_turn")
    async def begin_turn(self, message):
        async with self.lock:
            message_id = uuid5(NAMESPACE_URL, "kaufmann:voice:" + message.id)
            if message_id != self.message_id:
                result = self.remember(
                    await self.engine.record_user_message(message_id)
                )
                if result["status"] != "ok":
                    self.state = None
                    self.message_id = None
                    return result
                self.message_id = message_id
                self.request = message.text_content or ""
            else:
                result = {"status": "ok", "state": self.state}
            return result

    @timed("runtime.refresh")
    async def refresh(self):
        async with self.lock:
            return self.remember(await self.engine.get_state())

    def bind_speech(self, handle):
        if handle and handle.id not in self.speech_turns:
            self.speech_turns[handle.id] = self.message_id

    def allowed(self, handle):
        return (
            handle is not None
            and not handle.interrupted
            and self.message_id is not None
            and self.speech_turns.get(handle.id) == self.message_id
        )

    @timed("runtime.mutate")
    async def mutate(self, handle, operation, **arguments):
        async with self.lock:
            if not self.allowed(handle) or self.state is None:
                return {"status": "user_turn_required"}
            if operation == "approve_budget_exception":
                if not self.budget_token:
                    return {"status": "stale_exception"}
                arguments.update(
                    token=self.budget_token, approval_message_id=self.message_id
                )
            if operation == "confirm_order":
                if not self.review_token:
                    return {"status": "stale_token"}
                arguments.update(
                    token=self.review_token, approval_message_id=self.message_id
                )
            result = self.remember(
                await getattr(self.engine, operation)(
                    expected_version=self.state["version"], **arguments
                )
            )
            if (
                result["status"] == "ok"
                and result.get("changed")
                and operation in {"add_item", "approve_budget_exception"}
            ):
                result["navigation_status"] = await self.navigate(
                    {"type": "cart", "version": self.state["version"]}
                )
            if operation == "resolve_reference" and result["status"] == "ok":
                self.focused_product = {"id": result["product_id"]}
                result["navigation_status"] = await self.navigate(
                    {
                        "type": "product",
                        "product_id": result["product_id"],
                        "version": self.state["version"],
                    }
                )
            if operation == "prepare_order" and result["status"] == "ok":
                self.review_token = result["pending_token"]
                self.review_version = result["read_back"]["version"]
            return result

    @timed("runtime.search")
    async def search(self, handle, **arguments):
        async with self.lock:
            if not self.allowed(handle) or self.state is None:
                return {"status": "user_turn_required"}
            signature = tuple(
                (key, json.dumps(arguments.get(key), sort_keys=True))
                for key in (
                    "query",
                    "category",
                    "max_price_paise",
                    "min_price_paise",
                    "sort_by",
                    "filters",
                    "min_rating",
                    "availability",
                )
            )
            requested_offset = arguments.get("offset", 0)
            if signature == self.last_search_signature and requested_offset == 0:
                requested_offset = self.last_search_offset + arguments.get("limit", 3)
            arguments["offset"] = requested_offset
            result = await self.catalog.search(**arguments)
            if result["status"] not in {"ok", "not_found"}:
                return result
            self.last_search_signature = signature
            self.last_search_offset = requested_offset
            self.last_search_arguments = {
                key: value.copy() if isinstance(value, dict) else value
                for key, value in arguments.items()
            }
            saved = self.remember(
                await self.engine.update_context(
                    self.state["version"],
                    result_ids=[product["id"] for product in result["products"]],
                )
            )
            if saved["status"] != "ok":
                return saved
            self.speech_names = [
                product["name"] for product in result["products"] if product.get("name")
            ]
            for product in result["products"]:
                if self.focused_product and self.focused_product["id"] == product["id"]:
                    self.focused_product = product
            await self.navigate(
                {
                    "type": "catalog",
                    "query": arguments.get("query", ""),
                    "category": arguments.get("category", ""),
                    "max_price_paise": arguments.get("max_price_paise"),
                    "min_price_paise": arguments.get("min_price_paise"),
                    "sort_by": arguments.get("sort_by", "relevance"),
                    "filters": arguments.get("filters") or {},
                    "min_rating": arguments.get("min_rating"),
                    "availability": arguments.get("availability", "discoverable"),
                    "offset": requested_offset,
                    "focus_product_id": result["products"][0]["id"]
                    if result["products"]
                    else None,
                    "version": self.state["version"],
                }
            )
            return {**result, "state": self.state}

    async def search_more(self, handle):
        if self.last_search_arguments is None:
            return {"status": "not_found", "products": [], "has_more": False}
        arguments = dict(self.last_search_arguments)
        arguments["offset"] = self.last_search_offset + arguments.get("limit", 3)
        return await self.search(handle, **arguments)

    async def search_closest(self, handle, *, relax_fields, filters=None, **arguments):
        filters = filters or {}
        if (
            not isinstance(relax_fields, list)
            or len(relax_fields) > 10
            or any(not isinstance(field, str) for field in relax_fields)
        ):
            return {"status": "invalid_input", "products": []}
        relaxed = {
            field: filters[field]
            for field in dict.fromkeys(relax_fields)
            if field in filters
        }
        rating = arguments.get("min_rating")
        if "rating" in relax_fields and rating is not None:
            relaxed["rating"] = rating
        if not relaxed:
            return {"status": "invalid_input", "products": []}
        remaining = {key: value for key, value in filters.items() if key not in relaxed}
        search_arguments = dict(arguments)
        search_arguments["min_rating"] = None if "rating" in relax_fields else rating
        result = await self.search(
            handle, **search_arguments, filters=remaining, limit=3, offset=0
        )
        if result.get("status") == "ok":
            result["status"] = "alternatives"
            result["exact_match"] = False
            result["relaxed_filters"] = relaxed
        return result

    async def navigate(self, event):
        if self.publish_navigation is None:
            return "not_connected"
        return await self.publish_navigation(event)

    @timed("runtime.present_product")
    async def present_product(self, product_id, handle=None):
        if handle is not None and not self.allowed(handle):
            return {"status": "user_turn_required"}
        result = await self.catalog.get(product_id)
        if handle is not None and not self.allowed(handle):
            return {"status": "user_turn_required"}
        if result["status"] == "ok":
            self.focused_product = result["product"]
            result["navigation_status"] = await self.navigate(
                {
                    "type": "product",
                    "product_id": product_id,
                    "version": self.state["version"] if self.state else 0,
                }
            )
        return result

    @timed("runtime.select_product")
    async def select_product(self, product_id):
        async with self.lock:
            result = await self.catalog.get(product_id)
            if result["status"] != "ok":
                return result
            if self.review_token:
                canceled = self.remember(
                    await self.engine.interrupt_review(self.review_token)
                )
                if canceled["status"] != "ok":
                    return canceled
            refreshed = self.remember(await self.engine.get_state())
            if refreshed["status"] != "ok":
                return refreshed
            if self.state["result_ids"] == [product_id]:
                saved = refreshed
            else:
                saved = self.remember(
                    await self.engine.update_context(
                        self.state["version"], result_ids=[product_id]
                    )
                )
            if saved["status"] == "ok":
                self.focused_product = result["product"]
            return saved

    async def cancel_review(self, handle=None):
        async with self.lock:
            if handle is not None and not self.allowed(handle):
                return {"status": "user_turn_required"}
            if not self.review_token:
                return {"status": "ok"}
            token = self.review_token
            return self.remember(await self.engine.interrupt_review(token))

    async def deliver_review(self, token, handle):
        try:
            await handle.wait_for_playout()
            async with self.lock:
                spoken = [
                    item
                    for item in handle.chat_items
                    if getattr(item, "role", None) == "assistant"
                    and getattr(item, "text_content", "")
                ]
                if handle.interrupted or handle.exception() is not None or not spoken:
                    return self.remember(await self.engine.interrupt_review(token))
                return self.remember(
                    await self.engine.record_review_delivery(token, uuid4())
                )
        except BaseException:
            await self.engine.interrupt_review(token)
            raise

    def protected_speech(self):
        names = list(self.speech_names)
        if self.focused_product:
            names.extend(
                self.focused_product.get(key, "") for key in ("name", "name_te")
            )
        for item in (self.state or {}).get("items", []):
            names.extend(item.get(key, "") for key in ("name", "name_te"))
        return [name for name in names if isinstance(name, str) and name]

    def context(self):
        return json.dumps(
            {
                "state": voice_result(self.state),
                "current_user_request": self.request,
                "selected_product": voice_result(self.focused_product),
            },
            ensure_ascii=False,
        )
