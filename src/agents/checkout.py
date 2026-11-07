from src.agents.concierge import Concierge
from src.tools.cart import CartTools
from src.tools.checkout import CheckoutTools


class CheckoutAgent(CheckoutTools, CartTools, Concierge):
    def __init__(self, runtime):
        super().__init__(
            runtime,
            " First inspect the persisted address. A correction such as change only my state is a PATCH, not a replacement: call set_address with only that field, preserve all others, and acknowledge only that change. Never ask for the whole address again. For a new incomplete address, save volunteered fields immediately and ask only for fields still missing. Do not prepare an order unless the shopper requested checkout. Prepare and speak an order review before confirmation. Confirmation must come from a later actual user turn after completed speech. A wait, correction or question is not approval. Do not prepare another review when an already delivered unchanged review is being approved.",
        )
