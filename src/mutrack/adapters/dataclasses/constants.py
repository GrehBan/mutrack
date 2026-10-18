"""Define reserved attribute names for dataclasses integration."""

from __future__ import annotations

from typing import Final

DATACLASS_SKIP_PREFIXES: Final[tuple[str, ...]] = ()

DATACLASS_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "__dataclass_fields__",
        "__dataclass_params__",
        "__post_init__",
    }
)
