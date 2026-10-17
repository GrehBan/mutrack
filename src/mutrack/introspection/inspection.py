from src.mutrack.introspection.constants import SKIP_ATTRS, STARTSWITH_SKIP_PREFIXES


def matches_attribute_rules(
    name: str,
    attrs: frozenset[str],
    prefixes: tuple[str, ...],
    /,
) -> bool:
    return name in attrs or name.startswith(prefixes)


def is_internal_attribute(name: str, /) -> bool:
    return matches_attribute_rules(name, SKIP_ATTRS, STARTSWITH_SKIP_PREFIXES)
