from mutrack.adapters.pydantic.constants import PYDANTIC_ATTRS, PYDANTIC_SKIP_PREFIXES, PYDANTIC_CLASS_ACCESS_ONLY
from mutrack.introspection.inspection import matches_attribute_rules


def is_pydantic_attribute(name: str, /) -> bool:
    return matches_attribute_rules(name, PYDANTIC_ATTRS, PYDANTIC_SKIP_PREFIXES)


def is_pydantic_class_access_only(name: str, /) -> bool:
    return name in PYDANTIC_CLASS_ACCESS_ONLY
