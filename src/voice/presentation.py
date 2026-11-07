PRIVATE_FIELDS = frozenset(
    {
        "pending_token",
        "exception_token",
        "session_id",
        "turn_seq",
        "latest_message_id",
        "message_ids",
        "specifications_raw",
    }
)


def number_words(value):
    small = [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    ]
    if value < 0:
        return "minus " + number_words(-value)
    if value < 20:
        return small[value]
    if value < 100:
        tens = (
            "",
            "",
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
        )
        return tens[value // 10] + (" " + small[value % 10] if value % 10 else "")
    for scale, name in (
        (10000000, "crore"),
        (100000, "lakh"),
        (1000, "thousand"),
        (100, "hundred"),
    ):
        if value >= scale:
            return (
                number_words(value // scale)
                + " "
                + name
                + (" " + number_words(value % scale) if value % scale else "")
            )


def spoken_amount(paise):
    if paise < 0:
        return "minus " + spoken_amount(-paise)
    rupees, remainder = divmod(paise, 100)
    result = number_words(rupees) + (" rupee" if rupees == 1 else " rupees")
    if remainder:
        result += (
            " and "
            + number_words(remainder)
            + (" paisa" if remainder == 1 else " paise")
        )
    return result


def voice_result(value):
    if isinstance(value, dict):
        result = {
            key: voice_result(item)
            for key, item in value.items()
            if key not in PRIVATE_FIELDS
        }
        for key, item in value.items():
            if key.endswith("_paise") and type(item) is int:
                result[key.removesuffix("_paise") + "_spoken"] = spoken_amount(item)
        return result
    if isinstance(value, list):
        return [voice_result(item) for item in value]
    return value
