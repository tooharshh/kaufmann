from typing import Literal

from livekit.agents import function_tool

from src.agents.concierge import Concierge
from src.tools.cart import CartTools
from src.tools.catalog import CatalogTools


class ShoppingAdvisor(CatalogTools, CartTools, Concierge):
    def __init__(self, runtime):
        super().__init__(
            runtime,
            " Discover products and compare source facts. Show at most three useful choices on screen and give one brief introduction; do not narrate each listing unless asked. Resolve references against saved ordering before editing the basket. Substitution requires the user's selected replacement; never silently replace items.",
        )

    @function_tool(
        description="Load short category-specific comparison guidance when useful for electronics, fashion or grocery products."
    )
    async def category_guidance(
        self, category: Literal["electronics", "fashion", "grocery"]
    ) -> dict:
        from src.agents.prompts import electronics, fashion, grocery

        guidance = {
            "electronics": electronics.GUIDANCE,
            "fashion": fashion.GUIDANCE,
            "grocery": grocery.GUIDANCE,
        }[category]
        if guidance not in self.instructions:
            await self.update_instructions(self.instructions + "\n" + guidance)
        return {"status": "ok", "guidance": guidance}
