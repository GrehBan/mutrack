"""Batch change notifications using per-object suppression state."""

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
    """Emit a change or defer it while suppression is active.

    Args:
        obj: Object whose stored state or fields are accessed.

    Returns:
        True when the caller should emit now; False when deferred.
    """
    if get_change_suppress_level(obj) > 0:
        set_pending_change(obj, True)
        return False

    return True


@contextmanager
def batch_changes(
    obj: ITrackable,
    /,
) -> Generator[None]:
    """Emit one notification when the outermost batch exits.

    Args:
        obj: Object whose stored state or fields are accessed.

    Yields:
        Control to the caller while change notifications are
        suppressed.
    """
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
