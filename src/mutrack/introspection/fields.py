"""Access stored fields for introspection models without assignment hooks."""

from __future__ import annotations

from collections.abc import Iterator

from mutrack.internal.object_access import iter_stored_fields
from mutrack.introspection.inspection import is_internal_attribute


def iter_object_fields(obj: object, /) -> Iterator[tuple[str, object]]:
    """Yield stored fields without descriptors or internal bookkeeping.

    Args:
        obj: Object whose stored state or fields are accessed.

    Yields:
        Stored field names and values excluding internal bookkeeping.
    """
    for name, value in iter_stored_fields(obj):
        if not is_internal_attribute(name):
            yield name, value
