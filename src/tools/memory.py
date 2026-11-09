import json
from typing import Literal

import psycopg
from livekit.agents import RunContext, function_tool
from psycopg_pool import PoolTimeout


class MemoryTools:
    @function_tool(
        description="Inspect relevant remembered shopping preferences, separated by shopper and recipient. Never use remembered prices or stock."
    )
    async def inspect_memory(
        self,
        key: Literal["size", "language", "brand", "material", "response_style"]
        | None = None,
        subject: str | None = None,
    ):
        if not self.runtime.memory:
            return {"status": "unavailable"}
        try:
            result = await self.runtime.memory.inspect()
        except (psycopg.Error, PoolTimeout, TimeoutError):
            return {"status": "unavailable"}
        # Explicit inspection includes scoped facts even without category keywords.
        available = [
            fact
            for fact in result["facts"]
            if (key is None or fact["key"] == key)
            and (subject is None or fact["subject"] == subject)
        ]
        facts, used = [], 0
        for fact in available:
            length = len(json.dumps(fact, ensure_ascii=False))
            if len(facts) == 8 or used + length > 2400:
                break
            facts.append(fact)
            used += length
        return {
            "status": "ok",
            "facts": facts,
            "has_more": len(available) > len(facts),
        }

    @function_tool(
        description="Immediately remember, correct or forget an explicitly requested stable NONSENSITIVE shopping preference. Never save addresses, contacts, health or personal details here. subject is self or recipient:NAME; use clothing scope for garment size, footwear for shoe size, general for language/response style. For forget, inspect_memory by subject/key first when the stored scope is unknown. A scope_required result is not success: use only the matching scope intended by the user. value may be the prior value or unknown. Task budgets and gifts are not durable preferences."
    )
    async def manage_memory(
        self,
        context: RunContext,
        operation: Literal["remember", "forget"],
        subject: str,
        scope: str,
        key: Literal["size", "language", "brand", "material", "response_style"],
        value: str,
    ):
        if not self.runtime.allowed(context.speech_handle):
            return {"status": "user_turn_required"}
        if not self.runtime.memory:
            return {"status": "unavailable"}
        from src.state.memory import memory_validation_error
        from src.state.session import Refusal

        try:
            result = await self.runtime.memory.change(
                operation,
                {"subject": subject, "scope": scope, "key": key, "value": value},
                self.runtime.message_id,
            )
            await self.runtime.refresh_memory()
            return result
        except Refusal as exc:
            return memory_validation_error(exc.status)
        except (psycopg.Error, PoolTimeout, TimeoutError):
            return {"status": "unavailable"}
