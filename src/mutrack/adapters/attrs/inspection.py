from mutrack.adapters.attrs.constants import ATTRS_ATTRS, ATTRS_SKIP_PREFIXES
from mutrack.introspection.inspection import matches_attribute_rules


def is_attrs_attribute(name: str, /) -> bool:
    return matches_attribute_rules(name, ATTRS_ATTRS, ATTRS_SKIP_PREFIXES)
