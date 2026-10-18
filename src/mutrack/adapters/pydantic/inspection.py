"""Identify reserved pydantic framework attributes."""

from mutrack.adapters.pydantic.constants import (
    PYDANTIC_ATTRS,
    PYDANTIC_CLASS_ACCESS_ONLY,
    PYDANTIC_SKIP_PREFIXES,
)
from mutrack.introspection.inspection import matches_attribute_rules


def is_pydantic_attribute(name: str, /) -> bool:
    """Check whether an attribute is reserved by Pydantic.

    Args:
        name: Stored attribute or declared field name.

    Returns:
        True when the requested condition matches.
    """
    return matches_attribute_rules(
        name, PYDANTIC_ATTRS, PYDANTIC_SKIP_PREFIXES
    )


def is_pydantic_class_access_only(name: str, /) -> bool:
    """Check whether Pydantic metadata must be read from the class.

    Args:
        name: Stored attribute or declared field name.

    Returns:
        True when the requested condition matches.
    """
    return name in PYDANTIC_CLASS_ACCESS_ONLY
