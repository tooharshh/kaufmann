from src.agents.concierge import Concierge
from src.tools.cart import CartTools
from src.tools.catalog import CatalogTools


class CartAgent(CartTools, CatalogTools, Concierge):
    def __init__(self, runtime):
        super().__init__(
            runtime,
            " Handle basket corrections and budgets. Adding two means increase by two; make it two means set the total quantity to two. Resolve the intended item first. Never treat a budget exception as a permanent budget increase.",
        )
