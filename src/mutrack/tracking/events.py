"""Propagate mutations from a Trackable child to its live parents."""

from __future__ import annotations

from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.trackable.protocols import ITrackable


def propagate_change(
    obj: ITrackable,
    /,
) -> None:
    """Notify each live direct parent that a child has changed.

    Args:
        obj: Object whose stored state or fields are accessed.
    """
    for state, _ in get_parents_snapshot(obj):
        parent = state.obj()

        if parent is None:
            continue

        parent.changed()
