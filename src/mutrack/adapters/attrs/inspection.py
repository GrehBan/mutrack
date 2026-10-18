"""Identify reserved attrs framework attributes."""

from mutrack.adapters.attrs.constants import ATTRS_ATTRS, ATTRS_SKIP_PREFIXES
from mutrack.introspection.inspection import matches_attribute_rules


def is_attrs_attribute(name: str, /) -> bool:
    """Check whether an attribute is reserved by attrs.

    Args:
        name: Stored attribute or declared field name.

    Returns:
        True when the requested condition matches.
    """
    return matches_attribute_rules(name, ATTRS_ATTRS, ATTRS_SKIP_PREFIXES)
