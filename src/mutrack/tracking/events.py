from __future__ import annotations

from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.trackable.protocols import ITrackable


def propagate_change(
    obj: ITrackable,
    /,
) -> None:
    for state, _ in get_parents_snapshot(obj):
        parent = state.obj()

        if parent is None:
            continue

        parent.changed()