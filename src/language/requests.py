"""Conservative Telugu/English lexical and amount aids, not an intent classifier.

Original text is always retained. Unrecognized vocabulary is left for the model.
This module never interprets approvals or authorizes an effect.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

GLOSSARY = {
    "my": ("naa", "naaku", "నా", "నాకు"),
    "i": ("nenu", "నేను"),
    "friend": ("snehithudiki", "snehitudiki", "స్నేహితుడికి", "స్నేహితురాలికి"),
    "brother": ("annayya", "annayyaki", "అన్నయ్య", "అన్నయ్యకి", "అన్నయ్యకు"),
    "gift": ("bahumathi", "bahumati", "బహుమతి", "బహుమతులు"),
    "want": ("kavali", "kaavali", "కావాలి"),
    "show": ("chupinchu", "choopinchu", "చూపించు", "చూపించండి"),
    "under": ("lopu", "లోపు"),
    "from": ("nunchi", "నుంచి"),
    "to": ("varaku", "వరకు"),
    "not": ("vaddu", "kaadu", "వద్దు", "కాదు"),
    "different": ("verevi", "వేరేవి"),
    "do not like": ("nachaledu", "నచ్చలేదు"),
    "these": ("ivi", "ఇవి"),
    "more": ("inko", "inkaa", "ఇంకో", "ఇంకా", "marikonni", "మరికొన్ని"),
    "add": ("kalupu", "కలుపు", "జోడించు"),
    "do": ("cheyyi", "cheyi", "చెయ్యి", "చేయి"),
    "change": ("marchu", "మార్చు"),
    "total": ("motham", "mottam", "మొత్తం"),
    "compare": ("polchu", "పోల్చు", "పోల్చి"),
    "second": ("rendo", "రెండో"),
    "about": ("gurinchi", "గురించి"),
    "remember": ("gurthunchuko", "gurtunchuko", "గుర్తుంచుకో", "గుర్తుంచుకోండి"),
    "forget": ("marchipo", "మర్చిపో", "మర్చిపోండి"),
    "usually": ("saadharananga", "sadharananga", "సాధారణంగా"),
    "wear": ("vesukuntaanu", "vesukuntanu", "వేసుకుంటాను"),
    "wears": ("vesukuntaadu", "vesukuntadu", "వేసుకుంటాడు"),
    "size": ("saizu", "సైజు", "సైజ్"),
    "clothing": ("battala", "battalu", "బట్టల", "బట్టలు"),
    "medium": ("మీడియం", "మీడియమ్"),
    "large": ("లార్జ్",),
    "blue": ("నీలం",),
    "red": ("ఎరుపు",),
    "cotton": ("కాటన్",),
    "shirt": ("షర్టు",),
    "shirts": ("షర్టులు", "షర్టుల"),
    "jewellery": ("nagalu", "నగలు"),
    "budget": ("బడ్జెట్",),
    "cart": ("కార్ట్",),
    "rupees": ("rupayalu", "roopayalu", "రూపాయలు", "రూపాయల", "రూపాయలు"),
    "zero": ("sunna", "సున్నా"),
    "one": ("okati", "oka", "ఒకటి", "ఒక"),
    "two": ("rendu", "రెండు"),
    "three": ("moodu", "మూడు"),
    "four": ("nalugu", "నాలుగు"),
    "five": ("aidu", "aidhu", "ayidu", "ఐదు"),
    "six": ("aaru", "ఆరు"),
    "seven": ("yedu", "edu", "ఏడు"),
    "eight": ("enimidi", "enim idhi", "enimidhi", "ఎనిమిది"),
    "nine": ("tommidi", "తొమ్మిది"),
    "ten": ("padi", "పది"),
    "twenty": ("iravai", "iravayi", "ఇరవై"),
    "fifty": ("yabhai", "yabai", "యాభై"),
    "hundred": ("vanda", "vandala", "vandhala", "vandhalu", "వంద", "వందల", "వందలు"),
    "thousand": ("veyyi", "veyi", "వెయ్యి", "వేల", "వేలు"),
    "lakh": ("laksha", "లక్ష", "లక్షలు"),
}
ALIASES = {alias: word for word, aliases in GLOSSARY.items() for alias in aliases}
WORDS = dict(
    zip(
        [
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
        ],
        range(20),
        strict=True,
    )
)
WORDS.update(
    dict(
        zip(
            [
                "twenty",
                "thirty",
                "forty",
                "fifty",
                "sixty",
                "seventy",
                "eighty",
                "ninety",
            ],
            range(20, 100, 10),
            strict=True,
        )
    )
)
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "k": 1000}
PATTERN = re.compile(
    r"(?<!\w)(?:\d+(?:\.\d+)?(?:k)?|"
    + "|".join(WORDS | SCALES)
    + r")(?:[ -]+(?:\d+(?:\.\d+)?|"
    + "|".join(WORDS | SCALES)
    + r"))*(?!\w)"
)
ALIAS_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True))
    + r")(?!\w)",
    re.IGNORECASE,
)


def number_value(text):
    total, current, previous = Decimal(0), Decimal(0), None
    seen_scales = set()
    try:
        tokens = re.findall(r"\d+(?:\.\d+)?|[a-z]+", text)
        for token in tokens:
            if token in SCALES:
                scale = SCALES[token]
                if scale in seen_scales:
                    return None
                seen_scales.add(scale)
                if scale == 100:
                    current = (current or 1) * 100
                else:
                    total += (current or 1) * scale
                    current = Decimal(0)
                previous = None
            else:
                value = Decimal(WORDS[token]) if token in WORDS else Decimal(token)
                if previous is not None and (previous < 20 or value >= 10):
                    return (
                        None  # Digit sequences/adjacent unrelated amounts are not sums.
                    )
                current += value
                previous = value
        result = total + current
        return result if result.is_finite() and 0 <= result < 10**14 else None
    except (InvalidOperation, KeyError):
        return None


def request_aids(original):
    original = original[:2000]
    normalized = unicodedata.normalize("NFKC", original).casefold()
    gloss = ALIAS_PATTERN.sub(
        lambda match: ALIASES[match.group().casefold()], normalized
    )
    numbers = []

    def replace(match):
        value = number_value(match.group())
        if value is None:
            return match.group()
        rendered = (
            format(value, "f").rstrip("0").rstrip(".")
            if "." in format(value, "f")
            else str(value)
        )
        numbers.append({"phrase": match.group(), "number": rendered})
        return rendered

    gloss = PATTERN.sub(replace, gloss)
    return {
        "original": original,
        "lexical_gloss": gloss,
        "number_readings": numbers[:12],
        "basis": "lexical aids only; infer intent and negation from the complete original request",
    }


def explicit_money_paise(original):
    """Return one unambiguous explicit rupee amount; otherwise defer to the model."""
    gloss = request_aids(original)["lexical_gloss"]
    numbers = list(re.finditer(r"(?<!\w)\d+(?:\.\d+)?(?!\w)", gloss))
    if len(numbers) != 1 or "paise" in gloss or "paisa" in gloss:
        return None
    match = numbers[0]
    if (
        gloss[: match.start()].rstrip().endswith("-")
        or re.search(r"\bminus\s*$", gloss[: match.start()])
        or re.search(r"\b(?:dollars?|usd|eur|euros?)\b", gloss)
    ):
        return None
    # A currency or explicitly stated budget establishes the units. Quantities don't.
    if not re.search(r"\b(?:rupees?|rs|budget)\b|₹", gloss):
        return None
    value = Decimal(match.group()) * 100
    return int(value) if value == value.to_integral_value() and value < 10**16 else None


def model_request_aids(original):
    """Keep the model payload small; original text already exists in turn context."""
    aids = request_aids(original)
    return {
        "lexical_gloss": aids["lexical_gloss"],
        "number_readings": aids["number_readings"],
    }


def amount_guard(original, operation, arguments):
    if operation == "set_budget" and arguments.get("budget_paise") is not None:
        expected = explicit_money_paise(original)
        if expected is not None and arguments["budget_paise"] != expected:
            return {
                "status": "amount_mismatch",
                "expected_budget_paise": expected,
                "instruction": "The stated rupee amount was converted incorrectly. Use this verified paise value; do not apply the previous amount.",
            }
    return None
