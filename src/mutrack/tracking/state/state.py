import weakref
import threading

from src.mutrack.tracking.state.protocols import IState
from src.mutrack.tracking.trackable.protocols import TrackableType_co, ITrackable
from src.mutrack.tracking.types import Key


class MutableState(IState[TrackableType_co]):
    """A mutable state object that can be tracked by child objects."""

    __slots__ = ("_ref", "_lock", "__weakref__")

    def __init__(self, obj: TrackableType_co):
        self._ref = weakref.ref(obj)
        self._lock = threading.RLock()

    def obj(self) -> TrackableType_co | None:
        return self._ref()

    def link(self, child: ITrackable, key: Key) -> None:
        with self._lock:
            child._parents[self] = key

    def unlink(self, child: ITrackable) -> None:
        with self._lock:
            child._parents.pop(self, None)
