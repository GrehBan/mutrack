"""Define reserved attribute names for attrs integration."""

from __future__ import annotations

from typing import Final

ATTRS_SKIP_PREFIXES: Final[tuple[str, ...]] = ("__attrs_",)


ATTRS_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "__attrs_attrs__",
        "__attrs_own_setattr__",
        "__attrs_post_init__",
        "__attrs_init__",
    }
)
