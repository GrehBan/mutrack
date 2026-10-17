from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from functools import cache
from types import NoneType
from typing import Final, TypeAlias, TypeGuard


Atomic: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | bytes
    | complex
    | frozenset[object]
    | uuid.UUID
    | datetime.date
    | datetime.time
    | Decimal
)


_ATOMIC_TYPES: Final[tuple[type, ...]] = (
    str,
    int,
    float,
    bool,
    NoneType,
    bytes,
    complex,
    frozenset,
    uuid.UUID,
    datetime.date,
    datetime.time,
    Decimal,
)

_ATOMIC_TYPES_SET: Final[frozenset[type]] = frozenset(_ATOMIC_TYPES)


@cache
def is_atomic_type(tp: type) -> bool:
    return tp in _ATOMIC_TYPES_SET or issubclass(tp, _ATOMIC_TYPES)


def is_atomic(value: object) -> TypeGuard[Atomic]:
    return is_atomic_type(type(value))