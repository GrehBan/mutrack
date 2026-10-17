from __future__ import annotations

import threading
from typing import cast

from mutrack.internal.attributes import PARENTS_LOCK_STORE
from mutrack.internal.object_access import raw_getattr, raw_setattr
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.types import Key

_LOCK_CREATION_LOCK = threading.Lock()


def _get_or_create_parents_lock(
    obj: ITrackable,
    /,
) -> threading.RLock:
    lock = raw_getattr(
        obj,
        PARENTS_LOCK_STORE,
        None,
    )

    if lock is not None:
        return cast(threading.RLock, lock)

    with _LOCK_CREATION_LOCK:
        lock = raw_getattr(
            obj,
            PARENTS_LOCK_STORE,
            None,
        )

        if lock is None:
            lock = threading.RLock()

            raw_setattr(
                obj,
                PARENTS_LOCK_STORE,
                lock,
            )

        return cast(threading.RLock, lock)


def link_parent(
    child: ITrackable,
    state: IState[ITrackable],
    key: Key,
    /,
) -> None:
    lock = _get_or_create_parents_lock(child)

    with lock:
        child._tracking_parents[state] = key


def unlink_parent(
    child: ITrackable,
    state: IState[ITrackable],
    /,
) -> None:
    lock = _get_or_create_parents_lock(child)

    with lock:
        child._tracking_parents.pop(state, None)


def get_parents_snapshot(
    obj: ITrackable,
    /,
) -> tuple[tuple[IState[ITrackable], Key], ...]:
    lock = _get_or_create_parents_lock(obj)

    with lock:
        return tuple(obj._tracking_parents.items())