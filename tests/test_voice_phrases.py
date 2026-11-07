import asyncio

from src.voice.phrases import PhraseTokenizer


def test_complete_sentence_is_delivered_without_future_tokens():
    async def run():
        stream = PhraseTokenizer().stream()
        stream.push_text("Here are some gift ideas.")
        async with asyncio.timeout(0.1):
            assert (await anext(stream)).token == "Here are some gift ideas."
        await stream.aclose()

    asyncio.run(run())


def test_fragmentation_preserves_words_prices_names_and_telugu():
    async def run():
        text = "Try Dr. Brown's No. 5 Mug. It costs Rs. 1,299.50. ఇది మంచి బహుమతి."
        tokenizer = PhraseTokenizer(lambda: ["Dr. Brown's No. 5 Mug"])
        stream = tokenizer.stream()
        for char in text:
            stream.push_text(char)
        stream.end_input()
        parts = [item.token async for item in stream]
        assert parts == [
            "Try Dr. Brown's No. 5 Mug.",
            " It costs Rs. 1,299.50.",
            " ఇది మంచి బహుమతి.",
        ]
        assert "".join(parts) == text

    asyncio.run(run())


def test_short_sentence_final_tail_and_cancellation():
    async def run():
        stream = PhraseTokenizer().stream()
        stream.push_text("Okay! I recommend the blue cup")
        assert (await anext(stream)).token == "Okay!"
        await stream.aclose()
        assert [part async for part in stream] == []
        assert PhraseTokenizer().tokenize("... !") == []
        assert PhraseTokenizer().tokenize("The total is nine hundred rupees") == [
            "The total is nine hundred rupees"
        ]

    asyncio.run(run())


def test_long_product_and_price_are_not_split_at_input_token_boundaries():
    async def run():
        name = "Acme Series 2.0 Travel Mug; Ocean Blue"
        text = f"The {name} costs nine hundred ninety nine rupees. Want more details?"
        stream = PhraseTokenizer(lambda: [name]).stream()
        for index in range(0, len(text), 3):
            stream.push_text(text[index : index + 3])
        stream.end_input()
        parts = [item.token async for item in stream]
        assert parts == [
            f"The {name} costs nine hundred ninety nine rupees.",
            " Want more details?",
        ]

    asyncio.run(run())
