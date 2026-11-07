import json


def parse_specifications(raw: str | None) -> dict[str, list[str]]:
    if not isinstance(raw, str) or not raw or len(raw) > 65536:
        return {}
    try:
        decoder = json.JSONDecoder()
        parts = []
        index = 0
        while index < len(raw):
            if raw[index] == '"':
                _, end = decoder.raw_decode(raw, index)
                parts.append(raw[index:end])
                index = end
            elif raw.startswith("=>", index):
                parts.append(":")
                index += 2
            else:
                parts.append(raw[index])
                index += 1
        data = json.loads("".join(parts))
    except (ValueError, RecursionError):
        return {}
    if not isinstance(data, dict):
        return {}
    entries = data.get("product_specification")
    if not isinstance(entries, list):
        return {}
    attributes = {}
    names = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name, value = entry.get("key"), entry.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        name, value = " ".join(name.split()), value.strip()
        if not name or not value:
            continue
        canonical = names.setdefault(name.casefold(), name)
        values = attributes.setdefault(canonical, [])
        if value not in values:
            values.append(value)
    return attributes
