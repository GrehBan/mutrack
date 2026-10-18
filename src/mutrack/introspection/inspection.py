"""Match object fields against internal attribute exclusion rules."""

from mutrack.introspection.constants import (
    SKIP_ATTRS,
    STARTSWITH_SKIP_PREFIXES,
)


def matches_attribute_rules(
    name: str,
    attrs: frozenset[str],
    prefixes: tuple[str, ...],
    /,
) -> bool:
    """Match an attribute name against exclusions and reserved prefixes.

    Args:
        name: Stored attribute or declared field name.
        attrs: Explicit attribute names excluded by the inspection
            rules.
        prefixes: Reserved prefixes identifying excluded attributes.

    Returns:
        True when a name or reserved prefix matches.
    """
    return name in attrs or name.startswith(prefixes)


def is_internal_attribute(name: str, /) -> bool:
    """Check whether an attribute belongs to internal bookkeeping.

    Args:
        name: Stored attribute or declared field name.

    Returns:
        True when the attribute must be excluded from traversal.
    """
    return matches_attribute_rules(name, SKIP_ATTRS, STARTSWITH_SKIP_PREFIXES)
