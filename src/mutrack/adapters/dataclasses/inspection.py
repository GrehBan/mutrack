from src.mutrack.adapters.dataclasses.constants import DATACLASS_ATTRS, DATACLASS_SKIP_PREFIXES
from src.mutrack.introspection.inspection import matches_attribute_rules


def is_dataclass_attribute(name: str, /) -> bool:
    return matches_attribute_rules(name, DATACLASS_ATTRS, DATACLASS_SKIP_PREFIXES)