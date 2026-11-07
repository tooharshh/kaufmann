from typing import Literal

from livekit.agents import ToolResult, function_tool

from src.agents.base import StoreAgent


class Concierge(StoreAgent):
    def __init__(self, runtime, purpose=""):
        super().__init__(
            runtime,
            purpose
            or "Route discovery and comparison to discover, basket edits to basket, and ordering or delivery details to checkout. Use focus_shopping to fulfill the current request.",
        )

    @function_tool(
        description="Choose the appropriate shopping phase for the user's current request, without announcing a transfer. State and the latest user request are supplied automatically."
    )
    async def focus_shopping(self, phase: Literal["discover", "basket", "checkout"]):
        from src.agents.cart import CartAgent
        from src.agents.checkout import CheckoutAgent
        from src.agents.shopping_advisor import ShoppingAdvisor

        agent = {
            "discover": ShoppingAdvisor,
            "basket": CartAgent,
            "checkout": CheckoutAgent,
        }[phase]
        return agent(self.runtime), ToolResult({"status": "ok"}, reply_required=False)
