from typing import Literal

from livekit.agents import RunContext, function_tool

from src.voice.presentation import voice_result


class CatalogTools:
    @function_tool(
        description="Search concrete English product keywords inferred from the shopper's intent, never their entire sentence. Spaces require all terms; uppercase OR means alternatives; minus excludes a term. For gifts choose plausible product types such as mug OR photo frame OR notebook, not cheap gift ideas. Put price ceilings in max_price_paise (500 rupees = 50000), not query text. category is a literal category substring, never an occasion or recipient. Use filters for color, size, gender, brand, material, occasion, fit, pattern, sleeve and type. All supplied filters are combined; omitted attributes stay unrestricted. min_rating is a numeric minimum from zero to five. availability available/out_of_stock/unknown/all uses demo inventory. sort_by supports relevance, price_asc, price_desc, rating_desc and newest (historical crawl date). Use catalog_filter_options for actual supported values. Preserve explicit constraints; at most one meaningful synonym retry for not_found, never for unavailable. Returns source facts and ordered IDs; never invent results."
    )
    async def search_products(
        self,
        context: RunContext,
        query: str = "",
        category: str = "",
        max_price_paise: int | None = None,
        min_price_paise: int | None = None,
        sort_by: Literal[
            "relevance", "price_asc", "price_desc", "rating_desc", "newest"
        ] = "relevance",
        filters: dict[str, str] | None = None,
        min_rating: float | None = None,
        availability: Literal[
            "discoverable", "all", "available", "out_of_stock", "unknown"
        ] = "discoverable",
        offset: int = 0,
    ) -> dict:
        return voice_result(
            await self.runtime.search(
                context.speech_handle,
                query=query,
                category=category,
                max_price_paise=max_price_paise,
                min_price_paise=min_price_paise,
                sort_by=sort_by,
                filters=filters,
                min_rating=min_rating,
                availability=availability,
                limit=3,
                offset=offset,
            )
        )

    @function_tool(
        description="Read actual catalog categories, listed attribute filter values and supported sorts before selecting unfamiliar values. Missing attributes are unknown; listed size is not variant stock."
    )
    async def catalog_filter_options(self) -> dict:
        return await self.runtime.catalog.filter_options()

    @function_tool(
        description="Show the specific product being discussed on the shopper screen and return its source specifications, price and demo availability. Use for the selected product when the shopper wants details."
    )
    async def product_details(self, context: RunContext, product_id: str) -> dict:
        return voice_result(
            await self.runtime.present_product(product_id, context.speech_handle)
        )

    @function_tool(
        description="Compare two to four known product IDs using catalog specifications. Missing values are unknown."
    )
    async def compare_products(self, product_ids: list[str]) -> dict:
        return voice_result(await self.runtime.catalog.compare(product_ids))

    @function_tool(
        description="Resolve the first, second or third item against the saved search ordering. Positions start at one."
    )
    async def resolve_product(self, context: RunContext, position: int) -> dict:
        return voice_result(
            await self.runtime.mutate(
                context.speech_handle, "resolve_reference", position=position
            )
        )
