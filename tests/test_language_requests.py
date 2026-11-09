import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.language.requests import amount_guard, explicit_money_paise, request_aids
from src.voice.runtime import VoiceRuntime


@pytest.mark.parametrize(
    "text,paise",
    [
        ("Set my budget to eight hundred rupees.", 80000),
        ("నా కార్ట్ బడ్జెట్ ఎనిమిది వందలు చెయ్యి.", 80000),
        ("Naa cart budget enimidhi vandhalu cheyyi.", 80000),
        ("Cart budget eight hundred ki change cheyyi.", 80000),
        ("Budget 1.5k rupees", 150000),
        ("Budget one thousand two hundred rupees", 120000),
        ("Budget ninety nine rupees", 9900),
        ("Budget ₹0.50", 50),
    ],
)
def test_source_amounts_across_scripts(text, paise):
    assert explicit_money_paise(text) == paise
    assert amount_guard(text, "set_budget", {"budget_paise": paise}) is None
    assert (
        amount_guard(text, "set_budget", {"budget_paise": paise * 100})["status"]
        == "amount_mismatch"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Make the quantity two.",
        "Budget 800 rupees and add two shirts.",
        "My postal code is 500001.",
        "Budget minus eight hundred rupees.",
        "Budget -800 rupees.",
        "Budget 800 dollars.",
        "Budget 800 paise.",
        "Budget one hundred and fifty rupees.",
    ],
)
def test_ambiguous_or_non_rupee_amounts_are_not_rewritten(text):
    assert explicit_money_paise(text) is None


def test_gloss_preserves_original_negation_correction_and_unknown_vocabulary():
    text = "Naa annayya usually large vesukuntaadu, gurthunchuko. Adhi naa size kaadu. UnseenBrand42."
    result = request_aids(text)
    assert result["original"] == text
    for word in ("brother", "large", "remember", "not", "unseenbrand42"):
        assert word in result["lexical_gloss"]
    assert "intent" not in result
    assert "approve" not in request_aids("yes")["number_readings"]


def test_amount_mismatch_never_reaches_the_commerce_engine():
    class Engine:
        def __init__(self):
            self.called = False

        async def set_budget(self, **kwargs):
            self.called = True
            return {"status": "ok"}

    async def run():
        engine = Engine()
        runtime = VoiceRuntime(engine, None)
        runtime.state = {"version": 0}
        runtime.request = "నా బడ్జెట్ ఎనిమిది వందలు చెయ్యి."
        runtime.message_id = uuid4()
        handle = SimpleNamespace(id="speech", interrupted=False)
        runtime.bind_speech(handle)
        result = await runtime.mutate(handle, "set_budget", budget_paise=80000000)
        assert (
            result["status"] == "amount_mismatch"
            and result["expected_budget_paise"] == 80000
        )
        assert not engine.called

    asyncio.run(run())
