"""Identify reserved dataclasses framework attributes."""

from mutrack.adapters.dataclasses.constants import (
    DATACLASS_ATTRS,
    DATACLASS_SKIP_PREFIXES,
)
from mutrack.introspection.inspection import matches_attribute_rules


def is_dataclass_attribute(name: str, /) -> bool:
    """Check whether an attribute is reserved by dataclasses.

    Args:
        name: Stored attribute or declared field name.

    Returns:
        True when the requested condition matches.
    """
    return matches_attribute_rules(
        name, DATACLASS_ATTRS, DATACLASS_SKIP_PREFIXES
    )
