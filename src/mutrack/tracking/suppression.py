from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from mutrack.tracking.access import (
    get_change_suppress_level,
    get_pending_change,
    set_change_suppress_level,
    set_pending_change,
)
from mutrack.tracking.trackable.protocols import ITrackable


def mark_change_or_defer(
    obj: ITrackable,
    /,
) -> bool:
    if get_change_suppress_level(obj) > 0:
        set_pending_change(obj, True)
        return False

    return True


@contextmanager
def batch_changes(
    obj: ITrackable,
    /,
) -> Generator[None]:
    level = get_change_suppress_level(obj)

    set_change_suppress_level(
        obj,
        level + 1,
    )

    try:
        yield
    finally:
        level = get_change_suppress_level(obj) - 1

        set_change_suppress_level(
            obj,
            level,
        )

        if level == 0 and get_pending_change(obj):
            set_pending_change(obj, False)
            obj.changed()
