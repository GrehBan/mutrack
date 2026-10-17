import weakref
import threading

from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import TrackableType_co, ITrackable
from mutrack.tracking.types import Key
from mutrack.tracking.parents import link_parent, unlink_parent


class MutableState(IState[TrackableType_co]):
    """A mutable state object that can be tracked by child objects."""

    __slots__ = ("_ref", "__weakref__")

    def __init__(self, obj: TrackableType_co):
        self._ref = weakref.ref(obj)

    def obj(self) -> TrackableType_co | None:
        return self._ref()

    def link(
        self,
        child: ITrackable,
        key: Key,
    ) -> None:
        link_parent(child, self, key)

    def unlink(
        self,
        child: ITrackable,
    ) -> None:
        unlink_parent(child, self)