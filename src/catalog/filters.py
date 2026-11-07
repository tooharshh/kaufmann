import re

ATTRIBUTES = {
    "color": ("color", "colour", "brand color", "color code"),
    "size": ("size", "size in number", "ring size", "bangle size"),
    "gender": ("ideal for", "gender"),
    "brand": ("brand",),
    "material": ("material", "fabric", "outer material"),
    "occasion": ("occasion",),
    "fit": ("fit", "brand fit"),
    "pattern": ("pattern",),
    "sleeve": ("sleeve",),
    "type": ("type",),
}
SORTS = ("relevance", "price_asc", "price_desc", "rating_desc", "newest")
RATING_SQL = "case when trim(coalesce(product_rating, '')) ~ '^[0-9]([.][0-9]+)?$' then case when trim(product_rating)::numeric between 0 and 5 then trim(product_rating)::numeric end end"


def attribute_pattern(name, value):
    value = value.strip().casefold()
    if name == "size":
        value = {
            "s": "small",
            "m": "medium",
            "l": "large",
            "xl": "xl",
            "xxl": "xxl",
        }.get(value, value)
        aliases = {"small": "(small|s)", "medium": "(medium|m)", "large": "(large|l)"}
        expression = aliases.get(value, re.escape(value))
    elif name == "gender":
        normalized = {
            "male": "men",
            "man": "men",
            "female": "women",
            "woman": "women",
        }.get(value, value)
        expression = {
            "men": "men('s)?",
            "women": "women('s)?",
            "boys": "boys?",
            "girls": "girls?",
        }.get(normalized, re.escape(normalized))
    else:
        expression = re.escape(value)
    if name != "brand":
        expression = (
            '(?:[^"\\\\]*[^[:alnum:]"\\\\])?'
            + expression
            + '(?:[^[:alnum:]"\\\\][^"\\\\]*)?'
        )
    keys = "|".join(re.escape(key) for key in ATTRIBUTES[name])
    return (
        r'"key"\s*(?:=>|:)\s*"(?:'
        + keys
        + r')"\s*,\s*"value"\s*(?:=>|:)\s*"'
        + expression
        + '"'
    )


def filter_sql():
    return "\n".join(
        f"and (%({name})s = '' or coalesce(product_specifications, '') ~* %({name}_pattern)s)"
        for name in ATTRIBUTES
    )
