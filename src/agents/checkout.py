from src.agents.concierge import Concierge
from src.tools.cart import CartTools
from src.tools.checkout import CheckoutTools


class CheckoutAgent(CheckoutTools, CartTools, Concierge):
    def __init__(self, runtime):
        super().__init__(
            runtime,
            " Collect volunteered delivery fields through propose_delivery_address, read back and wait for later approval. Ask only for missing fields. Save to the address book only when explicitly requested. Before checkout, ask once whether the shopper wants anything else added; skip that question if they already said they are done. Do not prepare an order until they say they are ready. Prepare and speak an order review before confirmation. Confirmation must come from a later actual user turn after completed speech. A wait, correction or question is not approval. Do not prepare another review when an already delivered unchanged review is being approved.",
        )
