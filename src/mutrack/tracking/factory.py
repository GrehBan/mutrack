"""Create lazily initialized weak parent mappings and state tokens."""

from __future__ import annotations

import threading
from weakref import WeakKeyDictionary

from mutrack.internal.attributes import PARENTS_STORE, STATE_STORE
from mutrack.internal.object_access import raw_setattr
from mutrack.tracking.access import get_parents, get_state
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.state.state import MutableState
from mutrack.tracking.trackable.protocols import (
    ITrackable,
    ParentsDictionary,
    TrackableType,
)

_STATE_CREATION_LOCK = threading.Lock()
_PARENTS_CREATION_LOCK = threading.Lock()


def create_parents() -> ParentsDictionary[ITrackable]:
    """Create an empty weak mapping of parent states to child keys.

    Returns:
        An empty weak mapping of parent states to key sets.
    """
    return WeakKeyDictionary()


def create_state(
    obj: TrackableType,
    /,
) -> IState[TrackableType]:
    """Create a state token that weakly references its owner.

    Args:
        obj: Trackable object whose bookkeeping is accessed.

    Returns:
        A new state token weakly referencing the owner.
    """
    return MutableState(obj)


def get_or_create_parents(obj: ITrackable) -> ParentsDictionary[ITrackable]:
    """Return the parent mapping, initializing it once when needed.

    Args:
        obj: Trackable object whose bookkeeping is accessed.

    Returns:
        The unique parent mapping associated with the object.
    """
    parents = get_parents(obj, None)
    if parents is not None:
        return parents

    with _PARENTS_CREATION_LOCK:
        parents = get_parents(obj, None)
        if parents is None:
            parents = create_parents()
        raw_setattr(obj, PARENTS_STORE, parents)
        return parents


def get_or_create_state(
    obj: TrackableType,
    /,
) -> IState[TrackableType]:
    """Return the state token, initializing it once when needed.

    Args:
        obj: Trackable object whose bookkeeping is accessed.

    Returns:
        The unique state token associated with the object.
    """
    state = get_state(obj, None)
    if state is not None:
        return state

    with _STATE_CREATION_LOCK:
        state = get_state(obj, None)
        if state is None:
            state = create_state(obj)
        raw_setattr(obj, STATE_STORE, state)

        return state
