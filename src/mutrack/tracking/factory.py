from weakref import WeakKeyDictionary

from mutrack.tracking.state.protocols import IState
from mutrack.tracking.state.state import MutableState
from mutrack.tracking.access import get_parents, get_state
from mutrack.internal.object_access import raw_setattr
from mutrack.tracking.trackable.protocols import (
    ITrackable,
    ParentsDictionary,
    TrackableType,
)
from mutrack.internal.attributes import PARENTS_STORE, STATE_STORE


def create_parents() -> ParentsDictionary[ITrackable]:
    parents: ParentsDictionary[ITrackable] = WeakKeyDictionary()
    return parents


def create_state(
    obj: TrackableType,
    /,
) -> IState[TrackableType]:
    return MutableState(obj)


def get_or_create_parents(obj: ITrackable) -> ParentsDictionary[ITrackable]:
    parents: ParentsDictionary[ITrackable] | None = get_parents(obj, None)
    if parents is None:
        parents = create_parents()
        raw_setattr(obj, PARENTS_STORE, parents)
    return parents


def get_or_create_state(
    obj: TrackableType,
    /,
) -> IState[TrackableType]:
    state = get_state(obj, None)
    if state is None:
        state = create_state(obj)
        raw_setattr(obj, STATE_STORE, state)
    return state

