from livekit.agents import RunContext, function_tool

from src.voice.presentation import voice_result


class CartTools:
    @function_tool(
        description="Add a positive quantity of a known product to the basket. Adds to its existing quantity. An over_budget result requires a later explicit scoped exception approval."
    )
    async def add_item(
        self, context: RunContext, product_id: str, quantity: int
    ) -> dict:
        return voice_result(
            await self.runtime.mutate(
                context.speech_handle,
                "add_item",
                product_id=product_id,
                quantity=quantity,
            )
        )

    @function_tool(
        description="Correct a basket item's quantity to an exact number. Zero removes only that item. Never use this to add an increment."
    )
    async def set_quantity(
        self, context: RunContext, product_id: str, quantity: int
    ) -> dict:
        return voice_result(
            await self.runtime.mutate(
                context.speech_handle,
                "set_quantity",
                product_id=product_id,
                quantity=quantity,
            )
        )

    @function_tool(
        description="Set the standing budget in integer paise, or null to explicitly clear it. A one-time exception does not change this budget."
    )
    async def set_budget(self, context: RunContext, budget_paise: int | None) -> dict:
        return voice_result(
            await self.runtime.mutate(
                context.speech_handle, "set_budget", budget_paise=budget_paise
            )
        )

    @function_tool(
        description="Approve only the pending budget exception after a later user message explicitly agrees. Do not call for questions, refusal, quoted approval or conditional changes."
    )
    async def approve_budget_exception(self, context: RunContext) -> dict:
        return voice_result(
            await self.runtime.mutate(context.speech_handle, "approve_budget_exception")
        )
