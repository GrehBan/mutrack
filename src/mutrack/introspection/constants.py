from __future__ import annotations

from typing import Final

from mutrack.internal.attributes import (
    PARENTS,
    PARENTS_STORE,
    STATE,
    STATE_STORE,
    PENDING_CHANGE_STORE,
    MAX_DEPTH_LIMIT,
    CHANGE_SUPPRESS_LEVEL_STORE,
    PARENTS_LOCK_STORE
)


STARTSWITH_SKIP_PREFIXES: Final[tuple[str, ...]] = (
    "_sa_",
    "_abc_",
    "__private_"
)


CORE_SKIP_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "__dict__",
        "__class__",
        "__weakref__",
        "__annotations__",
        "__slots__",
        "__module__",
        "__doc__",
        "__qualname__",
        "__orig_class__",
        "__args__",
        "__parameters__",
        "__signature__",
        "__dir__",
        "__hash__",
        "__eq__",
        "__repr__",
        "__str__",
        "__getattribute__",
        "__setattr__",
        "__match_args__",
    }
)


LIB_ATTRS: Final[frozenset[str]] = frozenset(
    {
        PARENTS,
        PARENTS_STORE,
        STATE,
        STATE_STORE,
        CHANGE_SUPPRESS_LEVEL_STORE,
        PENDING_CHANGE_STORE,
        MAX_DEPTH_LIMIT,
        PARENTS_LOCK_STORE
    }
)


SKIP_ATTRS: Final[frozenset[str]] = (
    CORE_SKIP_ATTRS
    | LIB_ATTRS
)