"""Provide tracking.graph.traversal for mutation tracking."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Set

from mutrack.introspection.atomic import is_atomic
from mutrack.introspection.fields import iter_object_fields
from mutrack.tracking.types import Key


def iter_children(
    obj: object,
    /,
) -> Iterator[tuple[Key, object]]:
    """Yield direct children of an object without recursion.

    Args:
        obj: Object whose stored state or fields are accessed.

    Yields:
        A direct child location and its stored value.
    """
    if is_atomic(obj):
        return

    if isinstance(obj, Mapping):
        yield from obj.items()
        return

    if isinstance(obj, (list, tuple)):
        yield from enumerate(obj)
        return

    if isinstance(obj, Set):
        for value in obj:
            yield None, value
        return

    yield from iter_object_fields(obj)
