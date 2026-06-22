"""Helpers for normalizing public API response shapes."""


def to_camel(name: str) -> str:
    if name.startswith("_"):
        return name
    parts = name.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def camelize(value):
    if isinstance(value, dict):
        return {to_camel(k): camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camelize(item) for item in value]
    return value
