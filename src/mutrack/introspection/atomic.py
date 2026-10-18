"""Classify atomic values that terminate object-field traversal."""

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
    """Check whether a type represents an atomic traversal leaf.

    Args:
        tp: Type checked against the cached atomic-type classification.

    Returns:
        True when the type is classified as atomic.
    """
    return tp in _ATOMIC_TYPES_SET or issubclass(tp, _ATOMIC_TYPES)


def is_atomic(value: object) -> TypeGuard[Atomic]:
    """Check whether a value has no traversable children.

    Args:
        value: Object checked for classification as an atomic leaf.

    Returns:
        True when the value is an atomic traversal leaf.
    """
    value_type: type = type(value)
    return is_atomic_type(value_type)
